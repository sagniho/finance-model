import streamlit as st
import numpy as np
import numpy_financial as npf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# Calculation functions
def calculate_capex(project_data):
    return (project_data['epc_cost'] + project_data['interconnection_cost'] + 
            project_data['developer_fee'] + project_data['transaction_costs']) * project_data['project_size_dc'] * 1e6

def calculate_annual_production(project_data, year):
    initial_production = project_data['project_size_dc'] * project_data['production_yield'] * 1000
    # Adjust degradation start year if necessary
    if year >= project_data['degradation_start_year']:
        degradation_factor = (1 - project_data['degradation_rate']) ** (year - project_data['degradation_start_year'])
    else:
        degradation_factor = 1.0
    net_production = initial_production * degradation_factor
    return net_production

def calculate_revenue(project_data, year):
    net_production = calculate_annual_production(project_data, year)
    if year <= project_data['ppa_tenor']+1:
        # PPA price starts at initial rate and escalates annually
        ppa_price = project_data['ppa_rate'] * (1 + project_data['ppa_escalation']) ** (year - 1)
        revenue = net_production * ppa_price / 1000  # Convert to MWh
    else:
        merchant_price = project_data['merchant_price_start'] * (1 + project_data['merchant_escalation_rate']) ** (year)
        revenue = net_production * merchant_price / 1000

    return revenue

def calculate_operating_expenses(project_data, year):
    if year == 0:  # Year 0 only includes construction rent
        return project_data['construction_rent'] * project_data['site_acres']
    
    # For other years, calculate full breakdown of operating expenses
    escalation_factor = (1 + project_data['opex_escalation']) ** (year - 1)  # Start escalation from year 1 (after construction)
    
    # Calculate O&M and other expenses starting from year 1
    om_cost = project_data['om_cost'] * project_data['project_size_dc'] * 1000 * escalation_factor
    asset_management = project_data['asset_management_cost'] * project_data['project_size_dc'] * 1000 * escalation_factor
    insurance = project_data['insurance_cost'] * project_data['project_size_dc'] * 1000  # Assuming no escalation for insurance
    property_tax = project_data['property_tax'] * project_data['site_acres'] * escalation_factor
    inverter_replacement = project_data['inverter_replacement_cost'] * project_data['project_size_dc'] * 1000 if year >= 6 else 0
    rent = project_data['operating_rent'] * project_data['site_acres'] * escalation_factor
    
    total_opex = om_cost + asset_management + insurance + property_tax + inverter_replacement + rent
    return total_opex

def calculate_tax_equity(project_data):
    # Calculate CapEx (Capital Expenditures)
    capex = calculate_capex(project_data)
    
    # Calculate ITC (Investment Tax Credit)
    itc = capex * project_data['itc_amount'] * project_data['itc_eligible_portion']
    
    # Calculate FMV (Fair Market Value) with step-up
    fmv = itc * (1 + project_data['fmv_step_up'])  # FMV Step-up applied on ITC cost
    
    # Calculate tax equity investment based on ITC and a multiplier
    te_investment = itc * project_data['te_investment']  # TE Investment from ITC portion
    
    # Return the calculated values
    return {'itc': itc, 'fmv': fmv, 'te_investment': te_investment}


def calculate_cash_flows(project_data):
    capex = calculate_capex(project_data)
    tax_equity = calculate_tax_equity(project_data)
    
    cash_flows = []
    total_years = 1 + project_data['ppa_tenor'] + project_data['post_ppa_tenor']  # 1 year construction + PPA + post-PPA
    total_preferred_return = 0  # To track total preferred return

    for year in range(total_years):
        if year == 0:
            # Construction year
            revenue = 0
            opex = calculate_operating_expenses(project_data, year)  # Should only be construction rent
            EBITDA = revenue - opex  # Should be negative opex
            cash_flow = EBITDA - capex + tax_equity['fmv']
        else:
            revenue = calculate_revenue(project_data, year)
            opex = calculate_operating_expenses(project_data, year)
            EBITDA = revenue - opex

            # CapEx is zero in operating years
            capex_year = 0

            # Tax equity distributions
            if year <= project_data['buyout_year']:
                te_distribution = -tax_equity['fmv'] * project_data['preferred_return']  # Negative cash flow
                total_preferred_return += -te_distribution  # Accumulating positive amount
            else:
                te_distribution = 0

            if year == project_data['buyout_year']:
                buyout_cost = -tax_equity['fmv'] * project_data['buyout_percentage']  # Negative cash flow
            else:
                buyout_cost = 0

            # Tax equity cash flow is te_distribution + buyout_cost (both negative)
            tax_equity_cash_flow = te_distribution + buyout_cost

            cash_flow = EBITDA - capex_year + tax_equity_cash_flow

        cash_flows.append(cash_flow)

    remaining_itc_cash_flows = tax_equity['fmv'] - total_preferred_return - (tax_equity['fmv'] * project_data['buyout_percentage'])

    return cash_flows, remaining_itc_cash_flows

def calculate_irr(cash_flows):
    return npf.irr(cash_flows)

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

def generate_revenue_table(project_data):
    data = []
    start_year = project_data['construction_start'].year
    total_years = 1 + project_data['ppa_tenor'] + project_data['post_ppa_tenor']
    
    # Get CapEx and Tax Equity
    capex = calculate_capex(project_data)
    tax_equity = calculate_tax_equity(project_data)
    total_preferred_return = 0  # To track total preferred return

    for year in range(total_years):
        current_year = start_year + year
        
        if year == 0:
            # Year 0 (Construction Year)
            net_production = 0
            price = 0
            revenue_type = 'Construction'
            opex = calculate_operating_expenses(project_data, year)
            EBITDA = -opex  # No revenue in the construction year
            
            # Total cash flow for year 0
            total_cash_flow = EBITDA - capex + tax_equity['fmv']
        else:
            # PPA or Merchant years
            net_production = calculate_annual_production(project_data, year)
            if year <= project_data['ppa_tenor']+1:
                price = project_data['ppa_rate'] * (1 + project_data['ppa_escalation']) ** (year - 1)
                revenue_type = 'PPA'
            else:
                price = project_data['merchant_price_start'] * (1 + project_data['merchant_escalation_rate']) ** (year - 1)
                revenue_type = 'Merchant'
            
            revenue = net_production * price / 1000  # Convert kWh to MWh
            opex = calculate_operating_expenses(project_data, year)
            EBITDA = revenue - opex

            # CapEx is zero in operating years
            capex_year = 0

            # Tax equity distributions
            if year <= project_data['buyout_year']:
                te_distribution = -tax_equity['fmv'] * project_data['preferred_return']  # Negative cash flow
                total_preferred_return += -te_distribution  # Accumulating positive amount
            else:
                te_distribution = 0

            if year == project_data['buyout_year']:
                buyout_cost = -tax_equity['fmv'] * project_data['buyout_percentage']  # Negative cash flow
            else:
                buyout_cost = 0

            # Tax equity cash flow is te_distribution + buyout_cost (both negative)
            tax_equity_cash_flow = te_distribution + buyout_cost

            # Total cash flow for the year
            total_cash_flow = EBITDA - capex_year + tax_equity_cash_flow

        # Append each year's values to the DataFrame
        data.append({
            'Year': current_year,
            'Net Production (MWh)': net_production / 1000 if year > 0 else 0,
            'Price ($/MWh)': price if year > 0 else 0,
            'Revenue Type': revenue_type,
            'Revenue ($)': revenue if year > 0 else 0,
            'Operating Expenses ($)': opex,
            'EBITDA ($)': EBITDA,
            'Total Cash Flows ($)': total_cash_flow  # Updated Total Cash Flows calculation
        })
    
    revenue_df = pd.DataFrame(data)
    return revenue_df

# Streamlit app
def main():
    st.title('Solar Project Financial Model')

    st.sidebar.header('Project Inputs')
    with st.sidebar.expander("Project Specifications", expanded=True):
        project_size_dc = st.number_input('Project Size (MW-dc)', value=7.5, min_value=0.1)
        project_size_ac = st.number_input('Project Size (MW-ac)', value=5.0, min_value=0.1)
        site_acres = st.number_input('Site Acres', value=30.0, min_value=0.1)
        construction_rent = st.number_input('Construction Rent ($/acre/year)', value=600.0, min_value=0.0)
        operating_rent = st.number_input('Operating Rent ($/acre/year)', value=1200.0, min_value=0.0)
        developer_fee = st.number_input('Developer Fee ($/W-dc)', value=0.25, min_value=0.0, max_value=1.0)

    with st.sidebar.expander("Performance Parameters", expanded=True):
        production_yield = st.number_input('Production Yield (kWh/kWp)', value=1350, min_value=500, max_value=2500)
        degradation_rate = st.number_input('Annual Degradation Rate (%)', value=0.5, min_value=0.0, max_value=5.0) / 100

    with st.sidebar.expander("Financial Parameters", expanded=True):
        ppa_escalation = st.number_input('PPA Escalation (%)', value=2.0, min_value=0.0, max_value=10.0) / 100
        merchant_escalation_rate = st.number_input('Merchant Price Escalation (%)', value=1.5, min_value=0.0, max_value=10.0) / 100
        opex_escalation = st.number_input('OpEx Escalation (%)', value=2.0, min_value=0.0, max_value=10.0) / 100
        ppa_tenor = st.number_input('PPA Tenor (years)', value=20, min_value=1, max_value=30)
        post_ppa_tenor = st.number_input('Post-PPA Tenor (years)', value=16, min_value=0, max_value=30)
        tax_rate = st.number_input('Tax Rate (%)', value=21.0, min_value=0.0, max_value=100.0) / 100

    with st.sidebar.expander("Expense Inputs", expanded=True):
        om_cost = st.number_input('O&M Cost ($/kW/year)', value=6.00, min_value=0.0)
        asset_management_cost = st.number_input('Asset Management Cost ($/kW/year)', value=2.00, min_value=0.0)
        insurance_cost = st.number_input('Insurance Cost ($/kW/year)', value=4.50, min_value=0.0)
        property_tax = st.number_input('Property Tax ($/acre/year)', value=1200.00, min_value=0.0)
        inverter_replacement_cost = st.number_input('Inverter Replacement Cost ($/kW/year)', value=4.00, min_value=0.0)

    with st.sidebar.expander("CapEx Inputs", expanded=True):
        epc_cost = st.number_input('EPC Cost ($/W-dc)', value=1.65, min_value=0.0, max_value=5.0)
        interconnection_cost = st.number_input('Interconnection Cost ($/W-dc)', value=0.10, min_value=0.0, max_value=1.0)
        transaction_costs = st.number_input('Transaction Costs ($/W-dc)', value=0.07, min_value=0.0, max_value=1.0)

    with st.sidebar.expander("Tax Equity Inputs", expanded=True):
        itc_amount = st.number_input('ITC Amount (%)', value=30.0, min_value=0.0, max_value=100.0) / 100
        itc_eligible_portion = st.number_input('ITC-Eligible Portion (%)', value=95.0, min_value=0.0, max_value=100.0) / 100
        fmv_step_up = st.number_input('FMV Step-up (%)', value=30.0, min_value=0.0, max_value=100.0) / 100
        te_investment = st.number_input('TE Investment ($ of ITC)', value=1.15, min_value=0.0, max_value=5.0)
        preferred_return = st.number_input('Preferred Return (%)', value=2.5, min_value=0.0, max_value=20.0) / 100
        buyout_year = st.number_input('Buyout Year', value=7, min_value=1, max_value=20)
        buyout_percentage = st.number_input('Buyout (%)', value=7.25, min_value=0.0, max_value=100.0) / 100

    with st.sidebar.expander("Schedule", expanded=True):
        cod_date = st.date_input('Commercial Operation Date', value=datetime(2025, 12, 31))
        construction_start = st.date_input('Construction Start', value=datetime(2024, 12, 31))

    with st.sidebar.expander("Advanced Parameters", expanded=True):
        degradation_start_year = st.number_input('Degradation Start Year', value=1, min_value=1)
        ppa_escalation_start_year = st.number_input('PPA Escalation Start Year', value=2, min_value=1)
        ppa_rate = st.number_input('Initial PPA Rate ($/MWh)', value=114.05, min_value=0.0)
        merchant_price_start = st.number_input('Initial Merchant Price ($/MWh)', value=55.0, min_value=0.0)

    # Collect project data inputs
    project_data = {
        'project_size_dc': project_size_dc,
        'project_size_ac': project_size_ac,
        'site_acres': site_acres,
        'construction_rent': construction_rent,
        'operating_rent': operating_rent,
        'developer_fee': developer_fee,
        'production_yield': production_yield,
        'degradation_rate': degradation_rate,
        'ppa_rate': ppa_rate,
        'ppa_escalation': ppa_escalation,
        'merchant_price_start': merchant_price_start,
        'merchant_escalation_rate': merchant_escalation_rate,
        'opex_escalation': opex_escalation,
        'ppa_tenor': ppa_tenor,
        'post_ppa_tenor': post_ppa_tenor,
        'om_cost': om_cost,
        'asset_management_cost': asset_management_cost,
        'insurance_cost': insurance_cost,
        'property_tax': property_tax,
        'inverter_replacement_cost': inverter_replacement_cost,
        'epc_cost': epc_cost,
        'interconnection_cost': interconnection_cost,
        'transaction_costs': transaction_costs,
        'itc_amount': itc_amount,
        'itc_eligible_portion': itc_eligible_portion,
        'fmv_step_up': fmv_step_up,
        'te_investment': te_investment,
        'preferred_return': preferred_return,
        'buyout_year': buyout_year,
        'buyout_percentage': buyout_percentage,
        'cod_date': cod_date,
        'construction_start': construction_start,
        'degradation_start_year': degradation_start_year,
        'ppa_escalation_start_year': ppa_escalation_start_year,
        'tax_rate': tax_rate
    }

    if st.button('Calculate IRR'):
        cash_flows, remaining_itc_cash_flows = calculate_cash_flows(project_data)
        irr = calculate_irr(cash_flows)
        st.success(f'The project IRR is: {irr*100:.2f}%')

        # Generate revenue table with operating expenses and total cash flows
        revenue_df = generate_revenue_table(project_data)
        st.subheader("Annual Project Details")
        st.dataframe(revenue_df.style.format({
            'Net Production (MWh)': '{:,.0f}',
            'Price ($/MWh)': '${:,.2f}',
            'Revenue ($)': '${:,.0f}',
            'Operating Expenses ($)': '${:,.0f}',
            'EBITDA ($)': '${:,.0f}',
            'Total Cash Flows ($)': '${:,.0f}'
        }))
        
        # Calculate and display metrics
        total_revenue = revenue_df['Revenue ($)'].sum()
        total_operating_expenses = sum(calculate_operating_expenses(project_data, year) for year in range(1, project_data['ppa_tenor'] + project_data['post_ppa_tenor'] + 1))
        total_ebitda = total_revenue - total_operating_expenses
        total_cash_flows = sum(revenue_df['Total Cash Flows ($)'])

        st.subheader("Key Metrics")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total CapEx", f"${calculate_capex(project_data):,.0f}")
        with col2:
            st.metric("Total Operating Expenses", f"${total_operating_expenses:,.0f}")
        with col3:
            cumulative_cash_flows = np.cumsum(cash_flows)
            payback_years = np.argmax(cumulative_cash_flows > 0)
            st.metric("Payback Period", f"{payback_years} years")
        
        st.subheader("Total Project Metrics")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Revenue", f"${total_revenue:,.0f}")
        with col2:
            st.metric("Total EBITDA", f"${total_ebitda:,.0f}")
        with col3:
            st.metric("Total Cash Flows", f"${total_cash_flows:,.0f}")
        
        # Display total ITC cash flows left
        st.metric("Remaining ITC Cash Flows after Buyout", f"${remaining_itc_cash_flows:,.0f}")
        
        # Plot cash flows
        cash_flow_df = pd.DataFrame({
            'Year': range(len(cash_flows)),
            'Cash Flow': cash_flows,
            'Cumulative Cash Flow': np.cumsum(cash_flows)
        })
        st.plotly_chart(plot_cash_flows(cash_flow_df))


if __name__ == "__main__":
    main()
