import streamlit as st
import numpy as np
import numpy_financial as npf
import pandas as pd
import plotly.graph_objects as go
from openai import OpenAI
import io
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Font, Alignment, Border, Side

ASSISTANT_ID = st.secrets["NY_ADVISOR"],
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# Initialize session state
if 'thread' not in st.session_state:
    st.session_state['thread'] = client.beta.threads.create().id
if 'messages' not in st.session_state:
    st.session_state['messages'] = []
if 'project_data' not in st.session_state:
    st.session_state['project_data'] = {}
if 'calculated_results' not in st.session_state:
    st.session_state['calculated_results'] = None

def send_message_get_response(assistant_id, user_message):
    thread_id = st.session_state['thread']
    message = client.beta.threads.messages.create(
        thread_id=thread_id, role="user", content=user_message
    )
    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_id
    )
    while True:
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
        if run.status == "completed":
            messages = client.beta.threads.messages.list(thread_id=thread_id)
            latest_message = messages.data[0]
            text = latest_message.content[0].text.value
            return text

def get_gpt4_analysis(project_data, calculated_results):
    prompt = f"""
    Act as a financial analyst specializing in solar energy projects. Given the following project data and calculated results for a solar PPA (Power Purchase Agreement) C&I (rooftop or ground) project in NY, provide a brief analysis and suggestions. Keep in mind that this is C&I project and not a CSG:

    Project Data:
    - Project Capacity: {project_data['capacity']} MW
    - Capital Expenditure: ${project_data['capex']:,}
    - Annual Operational Expenditure: ${project_data['opex']:,}
    - Project Lifespan: {project_data['lifespan']} years
    - Annual Degradation Rate: {project_data['degradation_rate']*100}%
    - Annual Generation: {project_data['annual_generation']:,} kWh
    - Target IRR: {project_data['target_irr']}%
    - Inverter Replacement Cost: ${project_data['inverter_cost']:,}
    - Inverter Lifetime: {project_data['inverter_lifetime']} years
    - Incentives: ${project_data['incentives']:,}

    Calculated Results:
    - Required PPA Price: ${calculated_results['ppa_price']:.4f} per kWh
    - Total Generation: {calculated_results['total_generation']:.2f} GWh
    - Total Revenue: ${calculated_results['total_revenue']:,.2f}
    - Total OpEx: ${calculated_results['total_opex']:,.2f}
    - Net Profit: ${calculated_results['net_profit']:,.2f}

    Highlight any incentives applicable and analyze to optimize revenue from a regulatory perspective using your database.

    Limit your response to 250 words.
    """
    return send_message_get_response(ASSISTANT_ID, prompt)

def calculate_ppa_price(project_data):
    # Extract data from project_data
    capacity = project_data['capacity']
    capex = project_data['capex']
    opex = project_data['opex']
    lifespan = project_data['lifespan']
    degradation_rate = project_data['degradation_rate']
    annual_generation = project_data['annual_generation']
    target_irr = project_data['target_irr'] / 100  # Convert to decimal
    inverter_cost = project_data['inverter_cost']
    inverter_lifetime = project_data['inverter_lifetime']
    incentives = project_data['incentives']

    def npv_function(ppa_price):
        cash_flows = []
        for year in range(lifespan):
            year_generation = annual_generation * (1 - degradation_rate) ** year
            revenue = year_generation * ppa_price
            annual_cash_flow = revenue - opex
            if year == 0:
                annual_cash_flow += incentives
            if (year + 1) % inverter_lifetime == 0 and year + 1 != lifespan:
                annual_cash_flow -= inverter_cost
            cash_flows.append(annual_cash_flow)
        
        cash_flows.insert(0, -capex)
        
        return npf.npv(target_irr, cash_flows)

    low, high = 0, 1
    while high - low > 0.0001:
        mid = (low + high) / 2
        if npv_function(mid) < 0:
            low = mid
        else:
            high = mid
    
    return (low + high) / 2

def generate_cash_flow_df(project_data, ppa_price):
    capacity = project_data['capacity']
    capex = project_data['capex']
    opex = project_data['opex']
    lifespan = project_data['lifespan']
    degradation_rate = project_data['degradation_rate']
    annual_generation = project_data['annual_generation']
    inverter_cost = project_data['inverter_cost']
    inverter_lifetime = project_data['inverter_lifetime']
    incentives = project_data['incentives']

    data = []
    cumulative_cash_flow = -capex
    for year in range(lifespan):
        year_generation = annual_generation * (1 - degradation_rate) ** year
        revenue = year_generation * ppa_price
        inverter_replacement = inverter_cost if (year + 1) % inverter_lifetime == 0 and year + 1 != lifespan else 0
        cash_flow = revenue - opex - inverter_replacement
        if year == 0:
            cash_flow += incentives
        cumulative_cash_flow += cash_flow
        data.append({
            'Year': year + 1,
            'Annual Generation (kWh)': year_generation,
            'Revenue': revenue,
            'OpEx': opex,
            'Inverter Replacement': inverter_replacement,
            'Incentives': incentives if year == 0 else 0,
            'Cash Flow': cash_flow,
            'Cumulative Cash Flow': cumulative_cash_flow
        })
    return pd.DataFrame(data)

def plot_cash_flows(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['Year'], y=df['Cash Flow'], mode='lines+markers', name='Annual Cash Flow'))
    fig.add_trace(go.Scatter(x=df['Year'], y=df['Cumulative Cash Flow'], mode='lines+markers', name='Cumulative Cash Flow'))
    fig.update_layout(
        title='Project Cash Flows',
        xaxis_title='Year',
        yaxis_title='Cash Flow ($)',
        hovermode='x unified'
    )
    return fig

def export_to_excel(df, fig):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Cash Flows', index=False)
        workbook = writer.book
        worksheet = writer.sheets['Cash Flows']

        # Format the worksheet
        for column in worksheet.columns:
            max_length = 0
            column = [cell for cell in column]
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(cell.value)
                except:
                    pass
            adjusted_width = (max_length + 2)
            worksheet.column_dimensions[column[0].column_letter].width = adjusted_width

        # Add styles
        header_font = Font(bold=True)
        centered_alignment = Alignment(horizontal='center')
        border_style = Border(left=Side(style='thin'), 
                              right=Side(style='thin'), 
                              top=Side(style='thin'), 
                              bottom=Side(style='thin'))

        for cell in worksheet[1]:
            cell.font = header_font
            cell.alignment = centered_alignment
            cell.border = border_style

        for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=1, max_col=worksheet.max_column):
            for cell in row:
                cell.border = border_style

        # Add chart
        chart_sheet = workbook.create_sheet(title='Cash Flow Chart')
        chart = LineChart()
        chart.title = 'Project Cash Flows'
        chart.x_axis.title = 'Year'
        chart.y_axis.title = 'Cash Flow ($)'

        data = Reference(worksheet, min_col=7, min_row=1, max_col=8, max_row=len(df)+1)
        chart.add_data(data, titles_from_data=True)
        dates = Reference(worksheet, min_col=1, min_row=2, max_row=len(df)+1)
        chart.set_categories(dates)

        chart_sheet.add_chart(chart, 'B2')

    return buffer

def calculate_and_display_results(project_data):
    ppa_price = calculate_ppa_price(project_data)
    
    st.success(f'The required PPA price to achieve a {project_data["target_irr"]}% IRR is: ${ppa_price:.4f} per kWh')

    df = generate_cash_flow_df(project_data, ppa_price)

    total_generation = df['Annual Generation (kWh)'].sum()
    total_revenue = df['Revenue'].sum()
    total_opex = df['OpEx'].sum()
    total_inverter_cost = df['Inverter Replacement'].sum()
    net_profit = total_revenue - total_opex - total_inverter_cost - project_data['capex'] + project_data['incentives']

    st.subheader('Project Metrics')
    col1, col2 = st.columns(2)
    with col1:
        st.metric('Total Generation', f'{total_generation/1e6:.2f} GWh')
        st.metric('Total Revenue', f'${total_revenue/1e6:.2f}M')
    with col2:
        st.metric('Total OpEx', f'${total_opex/1e6:.2f}M')
        st.metric('Net Profit', f'${net_profit/1e6:.2f}M')

    st.subheader('Cash Flow Table')
    st.dataframe(df.style.format({
        'Annual Generation (kWh)': '{:,.0f}',
        'Revenue': '${:,.2f}',
        'OpEx': '${:,.2f}',
        'Inverter Replacement': '${:,.2f}',
        'Incentives': '${:,.2f}',
        'Cash Flow': '${:,.2f}',
        'Cumulative Cash Flow': '${:,.2f}'
    }))

    st.subheader('Interactive Cash Flow Graph')
    fig = plot_cash_flows(df)
    st.plotly_chart(fig, use_container_width=True)

    excel_buffer = export_to_excel(df, fig)
    st.download_button(
        label="Download Excel Report",
        data=excel_buffer.getvalue(),
        file_name="solar_ppa_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.session_state.calculated_results = {
        'ppa_price': ppa_price,
        'total_generation': total_generation/1e6,
        'total_revenue': total_revenue,
        'total_opex': total_opex,
        'net_profit': net_profit
    }

def calculate_results(project_data):
    ppa_price = calculate_ppa_price(project_data)
    df = generate_cash_flow_df(project_data, ppa_price)
    
    total_generation = df['Annual Generation (kWh)'].sum()
    total_revenue = df['Revenue'].sum()
    total_opex = df['OpEx'].sum()
    total_inverter_cost = df['Inverter Replacement'].sum()
    net_profit = total_revenue - total_opex - total_inverter_cost - project_data['capex'] + project_data['incentives']

    results = {
        'ppa_price': ppa_price,
        'df': df,
        'total_generation': total_generation,
        'total_revenue': total_revenue,
        'total_opex': total_opex,
        'net_profit': net_profit
    }
    
    return results

def display_results(results):
    st.success(f'The required PPA price to achieve a {st.session_state.project_data["target_irr"]}% IRR is: ${results["ppa_price"]:.4f} per kWh')

    st.subheader('Project Metrics')
    col1, col2 = st.columns(2)
    with col1:
        st.metric('Total Generation', f'{results["total_generation"]/1e6:.2f} GWh')
        st.metric('Total Revenue', f'${results["total_revenue"]/1e6:.2f}M')
    with col2:
        st.metric('Total OpEx', f'${results["total_opex"]/1e6:.2f}M')
        st.metric('Net Profit', f'${results["net_profit"]/1e6:.2f}M')

    st.subheader('Cash Flow Table')
    st.dataframe(results['df'].style.format({
        'Annual Generation (kWh)': '{:,.0f}',
        'Revenue': '${:,.2f}',
        'OpEx': '${:,.2f}',
        'Inverter Replacement': '${:,.2f}',
        'Incentives': '${:,.2f}',
        'Cash Flow': '${:,.2f}',
        'Cumulative Cash Flow': '${:,.2f}'
    }))

    st.subheader('Interactive Cash Flow Graph')
    fig = plot_cash_flows(results['df'])
    st.plotly_chart(fig, use_container_width=True)
    
def main():
    st.title('Solar PPA Price Calculator')

    st.sidebar.header('Project Inputs')
    with st.sidebar.expander("Project Specifications", expanded=True):
        project_capacity = st.number_input('Project Capacity (MW)', value=2.0, min_value=0.1, help="Total capacity of the solar project in megawatts")
        capex = st.number_input('Capital Expenditure (USD)', value=5000000, min_value=1, help="Total upfront cost for the project, including equipment and installation")
        opex = st.number_input('Annual Operational Expenditure (USD)', value=50000, min_value=0, help="Yearly cost for maintaining and operating the solar plant")
        project_lifespan = st.number_input('Project Lifespan (years)', value=25, min_value=1, max_value=50, help="Expected operational life of the project")

    with st.sidebar.expander("Performance Parameters", expanded=True):
        generation_method = st.radio("Generation Calculation Method", ["Annual Generation", "Peak Sun Hours"])
        
        if generation_method == "Annual Generation":
            annual_generation = st.number_input('Annual Generation (kWh)', value=80000, min_value=1, help="Expected annual electricity generation")
        else:
            peak_sun_hours = st.number_input('Peak Sun Hours per Day', value=5.0, min_value=1.0, max_value=12.0, help="Average daily hours of peak sunlight")
            system_efficiency = st.number_input('System Efficiency (%)', value=40.0, min_value=10.0, max_value=100.0, help="Overall efficiency of the solar power system") / 100
            annual_generation = project_capacity * 1000 * peak_sun_hours * 365 * system_efficiency

        degradation_rate = st.number_input('Annual Degradation Rate (%)', value=0.05, min_value=0.0, max_value=5.0, help="Yearly reduction in solar panel efficiency") / 100

    with st.sidebar.expander("Financial Parameters", expanded=True):
        target_irr = st.slider('Target IRR (%)', min_value=5.0, max_value=15.0, value=9.5, step=0.1, help="Internal Rate of Return goal for the project")
        inverter_cost = st.number_input('Inverter Replacement Cost (USD)', value=500000, min_value=0, help="Cost to replace inverters")
        inverter_lifetime = st.number_input('Inverter Lifetime (years)', value=10, min_value=1, max_value=25, help="Expected operational life of inverters")
        incentives = st.number_input('Incentives (USD)', value=0, min_value=0, help="Any upfront financial incentives or rebates")

    st.sidebar.markdown('---')
    st.sidebar.write('This calculator uses a simplified model and does not account for all real-world factors. Results should be used for estimation purposes only.')

    project_data = {
        'capacity': project_capacity,
        'capex': capex,
        'opex': opex,
        'lifespan': project_lifespan,
        'degradation_rate': degradation_rate,
        'annual_generation': annual_generation,
        'target_irr': target_irr,
        'inverter_cost': inverter_cost,
        'inverter_lifetime': inverter_lifetime,
        'incentives': incentives
    }

    st.session_state.project_data = project_data

    if st.button('Calculate PPA Price', key='calculate_ppa_button'):
        st.session_state.calculated_results = calculate_results(project_data)

    if st.session_state.calculated_results is not None:
        display_results(st.session_state.calculated_results)
        
        # Create download button only once
        excel_buffer = export_to_excel(st.session_state.calculated_results['df'], 
                                       plot_cash_flows(st.session_state.calculated_results['df']))
        st.download_button(
            label="Download Excel Report",
            data=excel_buffer.getvalue(),
            file_name="solar_ppa_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_excel_report"
        )

    show_ai_analysis = st.toggle('✨ Show AI Analysis', key='show_ai_analysis_toggle')

    if show_ai_analysis and st.session_state.calculated_results is not None:
        st.subheader("AI Analysis")
        with st.spinner('Generating AI analysis...'):
            analysis = get_gpt4_analysis(st.session_state.project_data, st.session_state.calculated_results)
        st.write(analysis)

    st.markdown("""
    ## Mathematical Concepts

    <details>
    <summary>Net Present Value (NPV)</summary>

    The Net Present Value (NPV) is calculated using the following formula:

    NPV = Σ (CF_t / (1+r)^t) for t = 0 to T

    Where:
    - $CF_t$ is the cash flow at time t
    - $r$ is the discount rate (in this case, the target IRR)
    - $T$ is the total number of time periods (project lifespan)

    The goal is to find the PPA price that makes NPV = 0.
    </details>

    <details>
    <summary>Internal Rate of Return (IRR)</summary>

    The Internal Rate of Return (IRR) is the discount rate that makes the NPV of all cash flows equal to zero. It's found by solving the equation:

    0 = Σ (CF_t / (1+IRR)^t) for t = 0 to T

    In our calculator, we use the target IRR as the discount rate and solve for the PPA price that achieves this IRR.
    </details>

    <details>
    <summary>Annual Cash Flow Calculation</summary>

    For each year t, the cash flow is calculated as:

    $$CF_t = (G_0 * (1-d)^t * P) - OpEx - I_t + Inc_t$$

    Where:
    - $G_0$ is the initial annual generation
    - $d$ is the annual degradation rate
    - $P$ is the PPA price
    - $OpEx$ is the annual operational expenditure
    - $I_t$ is the inverter replacement cost (if applicable in year t)
    - $Inc_t$ is the incentive (only applicable in year 0)
    </details>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
