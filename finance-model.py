import streamlit as st
import numpy as np
import numpy_financial as npf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import streamlit_authenticator as stauth

def add_custom_footer():
    st.markdown("""
    <style>
        /* Make the main container a flexbox */
        .reportview-container {
            display: flex;
            flex-direction: column;
            height: 100vh;
        }

        /* Make the content container grow to fill available space */
        .block-container {
            flex: 1;
        }

        /* Style for the footer */
        .footer {
            text-align: center;
            padding: 10px;
            background-color: #f1f1f1;
            position: relative;
            bottom: 0;
            width: 100%;
        }
    </style>
    """, unsafe_allow_html=True)

    # Add the footer content
    footer_html = """
    <div class="footer">
        <hr>
        <p>Aggreko Energy Transition Solutions 2024</p>
    </div>
    """
    st.markdown(footer_html, unsafe_allow_html=True)


merchant_price_curves = {
    'NY': {
        'years': list(range(2024, 2071)),
        'prices': [
            55.00, 55.83, 56.66, 57.51, 58.37, 59.25, 60.14, 61.04, 61.96, 62.89,
            63.83, 64.79, 65.76, 66.75, 67.75, 68.76, 69.79, 70.84, 71.90, 72.98,
            74.08, 75.19, 76.32, 77.46, 78.62, 79.80, 81.00, 82.21, 83.45, 84.70,
            85.97, 87.26, 88.57, 89.90, 91.24, 92.61, 94.00, 95.41, 96.84, 98.30,
            99.77, 101.27, 102.79, 104.33, 105.89, 107.48, 109.09
        ]
    },
    'CA': {
        'years': list(range(2024, 2071)),
        'prices': [50 + i * 0.85 for i in range(47)]  # Sample escalating prices
    },
    'IL': {
        'years': list(range(2024, 2071)),
        'prices': [45 + i * 0.75 for i in range(47)]  # Sample escalating prices
    },
    'TX': {
        'years': list(range(2024, 2071)),
        'prices': [40 + i * 0.65 for i in range(47)]  # Sample escalating prices
    }
}


def format_hover_value(value):
    if abs(value) >= 1e6:
        return f"${value/1e6:,.2f}MM"
    elif abs(value) >= 1e3:
        return f"${value/1e3:,.2f}k"
    else:
        return f"${value:,.2f}"

def plot_stacked_savings_chart(df):
    df = df[df['Year'] != 'Total']  # Exclude 'Total' row

    # Calculate total avoided cost in dollars
    df['Total Avoided Cost ($)'] = df['Avoided Cost Price ($/MWh)'] * df['Net Production (MWh)']
    df['Our Cost ($)'] = df['Our Price ($/MWh)'] * df['Net Production (MWh)']
    df['Savings ($)'] = df['Savings Unlocked ($)']

    # Create the stacked bar chart
    fig = go.Figure()

    # Our Cost
    fig.add_trace(go.Bar(
        x=df['Year'],
        y=df['Our Cost ($)'],
        name='Our Cost',
        marker_color='green',
        hovertemplate='Year: %{x}<br>Our Cost: %{customdata}<extra></extra>',
        customdata=df['Our Cost ($)'].apply(format_hover_value)
    ))

    # Savings
    fig.add_trace(go.Bar(
        x=df['Year'],
        y=df['Savings ($)'],
        name='Savings',
        marker_color='lightgreen',
        hovertemplate='Year: %{x}<br>Savings: %{customdata}<extra></extra>',
        customdata=df['Savings ($)'].apply(format_hover_value)
    ))

    fig.update_layout(
        barmode='stack',
        title='Total Avoided Cost Breakdown',
        xaxis_title='Year',
        yaxis_title='Cost ($)',
        hovermode='x unified',
        yaxis=dict(
            tickformat='$,',
            tickprefix='',
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )

    return fig

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

def calculate_revenue(project_data, year, state):
    net_production = calculate_annual_production(project_data, year)
    if year <= project_data['ppa_tenor'] + 1:
        # PPA price starts at initial rate and escalates annually
        ppa_price = project_data['ppa_rate'] * (1 + project_data['ppa_escalation']) ** (year - 1)
        revenue = net_production * ppa_price / 1000  # Convert to MWh
    else:
        # Use merchant price from the selected state's price curve
        merchant_year = project_data['construction_start'].year + year - 1
        try:
            index = merchant_price_curves[state]['years'].index(merchant_year)
            merchant_price = merchant_price_curves[state]['prices'][index]
        except ValueError:
            # If the year is not in the merchant price curve, use the last available price
            merchant_price = merchant_price_curves[state]['prices'][-1]
        revenue = net_production * merchant_price / 1000

    return revenue


def calculate_operating_expenses(project_data, year, rent_option):
    if year == 0:
        # Construction Rent based on the selected rent option for Year 0
        if rent_option == "Flat Lease/Year":
            construction_rent = project_data['construction_rent']
        elif rent_option == "$/Acre + Escalation":
            construction_rent = project_data['construction_rent'] * project_data['site_acres']
        elif rent_option == "$/MW-ac + Escalation":
            construction_rent = project_data['construction_rent'] * project_data['project_size_ac']
        
        # Return total operating expenses for Year 0 (only construction rent)
        return construction_rent
    
    # Initialize other expenses to zero for Year 1 onwards
    om_cost = 0
    asset_management = 0
    insurance = 0
    property_tax = 0
    inverter_replacement = 0
    rent = 0
    
    # Property Tax and Rent start from Year 1
    property_tax_escalation_factor = (1 + project_data['property_tax_escalation']) ** (year - 1)
    property_tax = project_data['property_tax'] * project_data['site_acres'] * property_tax_escalation_factor

    # Rent calculation based on the selected operating rent option
    if rent_option == "Flat Lease/Year":
        rent_escalation = (1 + project_data['rent_escalation']) ** (year - 1)
        rent = project_data['operating_rent'] * rent_escalation

    elif rent_option == "$/Acre + Escalation":
        rent_escalation_factor = (1 + project_data['rent_escalation']) ** (year - 1)
        rent = project_data['operating_rent'] * project_data['site_acres'] * rent_escalation_factor

    elif rent_option == "$/MW-ac + Escalation":
        rent_escalation = (1 + project_data['rent_escalation']) ** (year - 1)
        rent = project_data['operating_rent'] * project_data['project_size_ac'] * rent_escalation

    # Asset management cost escalates annually
    asset_management_escalation_factor = (1 + project_data['asset_management_escalation']) ** (year - 1)
    asset_management = project_data['asset_management_cost'] * project_data['project_size_dc'] * 1000 * asset_management_escalation_factor

    # Other Asset Management cost escalates annually
    other_asset_management_escalation_factor = (1 + project_data['other_asset_management_escalation']) ** (year - 1)
    other_asset_management = project_data['other_asset_management_cost'] * project_data['project_size_dc'] * 1000 * other_asset_management_escalation_factor

    
    # Insurance cost per MW-DC, no escalation assumed
    insurance = project_data['insurance_cost'] * project_data['project_size_dc'] * 1000  # Assuming insurance cost starts from Year 1
    
    if year >= 2:
        # O&M Costs start from Year 2 with escalation
        om_escalation_factor = (1 + project_data['om_escalation']) ** (year - 2)
        om_cost = project_data['om_cost'] * project_data['project_size_dc'] * 1000 * om_escalation_factor
        
    # Inverter Replacement costs apply only between Year 6 and Year 15, based on MW-AC
    if 6 <= year <= 15:
        inverter_replacement = project_data['inverter_replacement_cost'] * project_data['project_size_ac'] * 1000
    
    # Sum up all operating expenses
    total_opex = om_cost + asset_management + insurance + property_tax + inverter_replacement + rent + other_asset_management
    
    return total_opex




def calculate_tax_equity(project_data):
    # Calculate Total CapEx (including all components)
    total_capex = calculate_capex(project_data)
    
    # Calculate ITC Eligible CapEx (excluding Transaction Costs)
    itc_eligible_capex = (project_data['epc_cost'] + project_data['interconnection_cost'] + 
                          project_data['developer_fee']) * project_data['project_size_dc'] * 1e6
    
    # Calculate ITC (Investment Tax Credit)
    itc = itc_eligible_capex * project_data['itc_amount'] * project_data['itc_eligible_portion']
    
    # Calculate FMV (Fair Market Value) with step-up
    fmv = itc * (1 + project_data['fmv_step_up'])  # FMV Step-up applied on ITC
    
    # Calculate Tax Equity Investment based on ITC and a multiplier
    te_investment = itc * project_data['te_investment']
    
    # Display ITC and FMV values for debugging or informational purposes
    print(f"Calculated ITC Eligible CapEx: ${itc_eligible_capex:,.2f}")
    print(f"Calculated ITC: ${itc:,.2f}")
    print(f"Calculated FMV: ${fmv:,.2f}")
    
    # Return the calculated values
    return {'itc': itc, 'fmv': fmv, 'te_investment': te_investment}


def calculate_cash_flows(project_data, rent_option, state):
    capex = calculate_capex(project_data)
    tax_equity = calculate_tax_equity(project_data)
    
    cash_flows = []
    total_years = 1 + project_data['ppa_tenor'] + project_data['post_ppa_tenor']
    total_preferred_return = 0

    for year in range(total_years):
        if year == 0:
            # Construction year
            revenue = 0
            opex = calculate_operating_expenses(project_data, year, rent_option)
            EBITDA = revenue - opex
            cash_flow = EBITDA - capex + tax_equity['fmv']
        else:
            revenue = calculate_revenue(project_data, year, state)
            opex = calculate_operating_expenses(project_data, year, rent_option)
            EBITDA = revenue - opex

            # CapEx is zero in operating years
            capex_year = 0

            # Tax equity distributions
            if year <= project_data['buyout_year']:
                te_distribution = -tax_equity['fmv'] * project_data['preferred_return']
                total_preferred_return += -te_distribution
            else:
                te_distribution = 0

            if year == project_data['buyout_year']:
                buyout_cost = -tax_equity['fmv'] * project_data['buyout_percentage']
            else:
                buyout_cost = 0

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

def generate_revenue_table(project_data, rent_option, state):
    data = []
    start_year = project_data['construction_start'].year
    total_years = 1 + project_data['ppa_tenor'] + project_data['post_ppa_tenor']
    capex = calculate_capex(project_data)
    tax_equity = calculate_tax_equity(project_data)
    total_preferred_return = 0

    for year in range(total_years):
        current_year = start_year + year

        if year == 0:
            # Year 0 (Construction Year)
            net_production = 0
            price = 0
            avoided_price = 0
            revenue_type = 'Construction'
            savings = 0
            opex = calculate_operating_expenses(project_data, year, rent_option)
            EBITDA = -opex
            total_cash_flow = EBITDA - capex + tax_equity['fmv']
        else:
            net_production = calculate_annual_production(project_data, year)

            if year <= project_data['ppa_tenor']:
                # PPA term
                price = project_data['ppa_rate'] * (1 + project_data['ppa_escalation']) ** (year - 1)
                avoided_price = project_data['avoided_cost_ppa_price'] * (1 + project_data['avoided_cost_escalation']) ** (year - 1)
                revenue_type = 'PPA'
            else:
                # Merchant years
                merchant_year = start_year + year - 1
                try:
                    index = merchant_price_curves[state]['years'].index(merchant_year)
                    price = merchant_price_curves[state]['prices'][index]
                except ValueError:
                    price = merchant_price_curves[state]['prices'][-1]
                avoided_price = price  # After PPA, avoided cost price equals merchant price
                revenue_type = 'Merchant'

            # Calculate savings
            if price != avoided_price:
                savings = (avoided_price - price) * net_production / 1000
            else:
                savings = 0

            revenue = net_production * price / 1000
            opex = calculate_operating_expenses(project_data, year, rent_option)
            EBITDA = revenue - opex

            capex_year = 0

            # Tax equity distributions
            if year <= project_data['buyout_year']:
                te_distribution = -tax_equity['fmv'] * project_data['preferred_return']
                total_preferred_return += -te_distribution
            else:
                te_distribution = 0

            if year == project_data['buyout_year']:
                buyout_cost = -tax_equity['fmv'] * project_data['buyout_percentage']
            else:
                buyout_cost = 0

            tax_equity_cash_flow = te_distribution + buyout_cost
            total_cash_flow = EBITDA - capex_year + tax_equity_cash_flow

        data.append({
            'Year': current_year,
            'Net Production (MWh)': net_production / 1000 if year > 0 else 0,
            'Our Price ($/MWh)': price if year > 0 else 0,
            'Avoided Cost Price ($/MWh)': avoided_price if year > 0 else 0,
            'Revenue Type': revenue_type,
            'Revenue ($)': revenue if year > 0 else 0,
            'Operating Expenses ($)': opex,
            'EBITDA ($)': EBITDA,
            'Total Cash Flows ($)': total_cash_flow,
            'Savings Unlocked ($)': savings
        })

    revenue_df = pd.DataFrame(data)

    # Add totals row
    totals = revenue_df.select_dtypes(include=[np.number]).sum()
    totals['Year'] = 'Total'
    totals['Revenue Type'] = ''
    revenue_df = pd.concat([revenue_df, totals.to_frame().T], ignore_index=True)

    return revenue_df

# Main application function
def main():
    st.set_page_config(page_title='C&I PPA Model', page_icon='a.png', layout='wide')

    
    # Retrieve credentials from st.secrets
    admin_username = st.secrets["auth"]["admin_username"]
    admin_password = st.secrets["auth"]["admin_password"]
    user_username = st.secrets["auth"]["user_username"]
    user_password = st.secrets["auth"]["user_password"]

    # User Authentication
    names = ['Admin User', 'C&I User']
    usernames = [admin_username, user_username]
    passwords = [admin_password, user_password]

    hashed_passwords = stauth.Hasher(passwords).generate()

    credentials = {
        'usernames': {
            admin_username: {
                'name': 'Admin User',
                'password': hashed_passwords[0]
            },
            user_username: {
                'name': 'C&I User',
                'password': hashed_passwords[1]
            }
        }
    }

    authenticator = stauth.Authenticate(credentials, 'some_cookie_name', 'some_signature_key', cookie_expiry_days=30)

    name, authentication_status, username = authenticator.login('main')


    if authentication_status:
        authenticator.logout('Logout', location='sidebar')
        st.sidebar.write(f'Welcome *{name}*')

        # Determine user type
        if username == 'admin':
            user_type = 'admin'
        else:
            user_type = 'user'
            

        st.image('logo.png', width=150)
        st.title('C&I PPA Model')

        st.sidebar.header('Project Inputs')
        with st.sidebar.expander("Project Specifications", expanded=True):
            # Inputs always enabled for this section
            project_size_dc = st.number_input('Project Size (MW-dc)', value=7.5, min_value=0.1, disabled=False)
            project_size_ac = st.number_input('Project Size (MW-ac)', value=5.0, min_value=0.1, disabled=False)
            state = st.selectbox('Select State', ['NY', 'CA', 'IL', 'TX'])
            ppa_tenor = st.number_input('PPA Tenor (years)', value=20, min_value=1, max_value=30, disabled=False)
            post_ppa_tenor = st.number_input('Post-PPA Tenor (years)', value=16, min_value=0, max_value=30, disabled=False)
            itc_amount = st.number_input('ITC Amount (%)', value=30.0, min_value=0.0, max_value=100.0, disabled=False) / 100
            avoided_cost_ppa_price = st.number_input('Avoided PPA Price ($/MWh)', value=155.0, min_value=0.0, disabled=False)
            avoided_cost_escalation = st.number_input('Avoided Cost Escalation (%)', value=2.0, min_value=0.0, max_value=10.0, disabled=False) / 100
            production_yield = st.number_input('Production Yield (kWh/kWp)', value=1350, min_value=500, max_value=2500, disabled=False)
        
            # Rent option toggle for both construction and operating rents (now a radio button)
            rent_option = st.radio("Select Rent Calculation Method", 
                                   options=["Flat Lease/Year", "$/Acre + Escalation", "$/MW-ac + Escalation"], 
                                   index=0)  # Default selection is the first option
        
            # Initialize site_acres to a default value
            site_acres = 0
        
            # Construction Rent inputs based on the selected rent option
            if rent_option == "Flat Lease/Year":
                construction_rent = st.number_input('Construction Rent (Flat $/year)', value=50000.0, min_value=0.0, disabled=False)
                operating_rent = st.number_input('Operating Rent (Flat $/year)', value=36000.0, min_value=0.0, disabled=False)
                rent_escalation = st.number_input('Flat Lease Escalation (%)', value=2.0, min_value=0.0, max_value=10.0, disabled=False) / 100
        
            elif rent_option == "$/Acre + Escalation":
                construction_rent = st.number_input('Construction Rent ($/acre/year)', value=600.0, min_value=0.0, disabled=False)
                operating_rent = st.number_input('Operating Rent ($/acre/year)', value=1200.0, min_value=0.0, disabled=False)
                rent_escalation = st.number_input('Rent Escalation (%)', value=2.0, min_value=0.0, max_value=10.0, disabled=False) / 100
                site_acres = st.number_input('Site Acres', value=30.0, min_value=0.1, disabled=False)  # Only defined here
        
            elif rent_option == "$/MW-ac + Escalation":
                construction_rent = st.number_input('Construction Rent ($/MW-ac/year)', value=8000.0, min_value=0.0, disabled=False)
                operating_rent = st.number_input('Operating Rent ($/MW-ac/year)', value=25000.0, min_value=0.0, disabled=False)
                rent_escalation = st.number_input('MW-ac Rent Escalation (%)', value=2.0, min_value=0.0, max_value=10.0, disabled=False) / 100


        with st.sidebar.expander("Schedule", expanded=True):
            cod_date = st.date_input('Commercial Operation Date', value=datetime(2025, 12, 31), disabled=False)
            construction_start = st.date_input('Construction Start', value=datetime(2024, 12, 31), disabled=False)


        # For other sections, inputs are disabled for 'user' type
        disabled_input = (user_type == 'user')

        with st.sidebar.expander("Financial Parameters", expanded=False):
            ppa_escalation = st.number_input('PPA Escalation (%)', value=2.0, min_value=0.0, max_value=10.0, disabled=disabled_input) / 100
            merchant_escalation_rate = st.number_input('Merchant Price Escalation (%)', value=1.5, min_value=0.0, max_value=10.0, disabled=disabled_input) / 100
            opex_escalation = st.number_input('OpEx Escalation (%)', value=2.0, min_value=0.0, max_value=10.0, disabled=disabled_input) / 100
            tax_rate = st.number_input('Tax Rate (%)', value=21.0, min_value=0.0, max_value=100.0, disabled=disabled_input) / 100
            developer_fee = st.number_input('Developer Fee ($/W-dc)', value=0.25, min_value=0.0, max_value=1.0, disabled=disabled_input)

        with st.sidebar.expander("OpEx Inputs", expanded=False):
            om_cost = st.number_input('O&M Cost ($/kW/year)', value=6.00, min_value=0.0, disabled=disabled_input)
            om_escalation = st.number_input('O&M Escalation (%)', value=2.0, min_value=0.0, max_value=10.0, disabled=disabled_input) / 100
            asset_management_cost = st.number_input('Asset Management Cost ($/kW/year)', value=2.00, min_value=0.0, disabled=disabled_input)
            asset_management_escalation = st.number_input('Asset Management Escalation (%)', value=1.5, min_value=0.0, max_value=10.0, disabled=disabled_input) / 100
            insurance_cost = st.number_input('Insurance Cost ($/kW/year)', value=4.50, min_value=0.0, disabled=disabled_input)
            property_tax = st.number_input('Property Tax ($/acre/year)', value=1200.00, min_value=0.0, disabled=disabled_input)
            property_tax_escalation = st.number_input('Property Tax Escalation (%)', value=2.0, min_value=0.0, max_value=10.0, disabled=disabled_input) / 100
            other_asset_management_cost = st.number_input('Other Asset Management Cost ($/kW/year)', value=5.00, min_value=0.0, disabled=disabled_input)
            other_asset_management_escalation = st.number_input('Other Asset Management Escalation (%)', value=2.0, min_value=0.0, max_value=10.0, disabled=disabled_input) / 100
            inverter_replacement_cost = st.number_input('Inverter Replacement Cost ($/kW/year)', value=4.00, min_value=0.0, disabled=disabled_input)

        with st.sidebar.expander("CapEx Inputs", expanded=False):
            epc_cost = st.number_input('EPC Cost ($/W-dc)', value=1.65, min_value=0.0, max_value=5.0, disabled=disabled_input)
            interconnection_cost = st.number_input('Interconnection Cost ($/W-dc)', value=0.10, min_value=0.0, max_value=1.0, disabled=disabled_input)
            transaction_costs = st.number_input('Transaction Costs ($/W-dc)', value=0.07, min_value=0.0, max_value=1.0, disabled=disabled_input)

        with st.sidebar.expander("Tax Equity Inputs", expanded=False):
            itc_eligible_portion = st.number_input('ITC-Eligible Portion (%)', value=95.0, min_value=0.0, max_value=100.0, disabled=disabled_input) / 100
            fmv_step_up = st.number_input('FMV Step-up (%)', value=30.0, min_value=0.0, max_value=100.0, disabled=disabled_input) / 100
            te_investment = st.number_input('TE Investment ($ of ITC)', value=1.15, min_value=0.0, max_value=5.0, disabled=disabled_input)
            preferred_return = st.number_input('Preferred Return (%)', value=2.5, min_value=0.0, max_value=20.0, disabled=disabled_input) / 100
            buyout_year = st.number_input('Buyout Year', value=7, min_value=1, max_value=20, disabled=disabled_input)
            buyout_percentage = st.number_input('Buyout (%)', value=7.25, min_value=0.0, max_value=100.0, disabled=disabled_input) / 100


        with st.sidebar.expander("Other Parameters", expanded=False):
            degradation_rate = st.number_input('Annual Degradation Rate (%)', value=0.5, min_value=0.0, max_value=5.0, disabled=disabled_input) / 100
            degradation_start_year = st.number_input('Degradation Start Year', value=1, min_value=1, disabled=disabled_input)
            ppa_escalation_start_year = st.number_input('PPA Escalation Start Year', value=2, min_value=1, disabled=disabled_input)
            ppa_rate = st.number_input('Initial PPA Rate ($/MWh)', value=114.05, min_value=0.0, disabled=disabled_input)
            merchant_price_start = st.number_input('Initial Merchant Price ($/MWh)', value=55.0, min_value=0.0, disabled=disabled_input)
            discount_rate = st.number_input('Discount Rate for NPV and LCOE (%)', value=8.0, min_value=0.0, max_value=100.0, disabled=False) / 100


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
            'om_escalation': om_escalation,
            'asset_management_escalation': asset_management_escalation,
            'property_tax_escalation': property_tax_escalation,
            'rent_escalation': rent_escalation,
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
            'tax_rate': tax_rate,
            'rent_option': rent_option,
            'avoided_cost_ppa_price': avoided_cost_ppa_price,
            'avoided_cost_escalation': avoided_cost_escalation,
            'other_asset_management_cost': other_asset_management_cost,
            'other_asset_management_escalation': other_asset_management_escalation,
            'discount_rate': discount_rate,
            'state': state
        }

        if st.button('Calculate IRR'):
            cash_flows, remaining_itc_cash_flows = calculate_cash_flows(project_data, rent_option, state)
            irr = calculate_irr(cash_flows)
            st.success(f'The project IRR is: {irr*100:.2f}%')

            # Generate revenue table with operating expenses and total cash flows
            revenue_df = generate_revenue_table(project_data, rent_option, state)

            # Calculate NPV
            NPV = npf.npv(discount_rate, cash_flows)
            
            # Calculate LCOE
            capex = calculate_capex(project_data)
            operating_expenses_list = revenue_df.loc[revenue_df['Year'] != 'Total', 'Operating Expenses ($)'].values
            net_production_list = revenue_df.loc[revenue_df['Year'] != 'Total', 'Net Production (MWh)'].values
            
            # Include CapEx in total costs list
            total_costs_list = [capex] + operating_expenses_list.tolist()
            # Include zero in net production list for year 0
            net_production_list_with_zero = [0] + net_production_list.tolist()
            
            # Calculate discounted costs and discounted energy production
            discounted_costs = [total_costs_list[t] / (1 + discount_rate) ** t for t in range(len(total_costs_list))]
            discounted_energy = [net_production_list_with_zero[t] / (1 + discount_rate) ** t for t in range(len(net_production_list_with_zero))]
            
            NPV_costs = sum(discounted_costs)
            NPV_energy = sum(discounted_energy)
            
            LCOE = NPV_costs / NPV_energy  # LCOE in $/MWh


            # Display Tax Equity Details
            #tax_equity = calculate_tax_equity(project_data)
            #st.subheader("Tax Equity Details")
            #st.write(f"**Calculated ITC Eligible CapEx:** ${tax_equity['itc'] / (project_data['itc_amount'] * project_data['itc_eligible_portion']):,.2f}")
            #st.write(f"**Calculated ITC:** ${tax_equity['itc']:,.2f}")
            #st.write(f"**Calculated FMV:** ${tax_equity['fmv']:,.2f}")

            
            

            st.subheader("Annual Project Details")
            st.dataframe(revenue_df.style.format({
                'Net Production (MWh)': '{:,.0f}',
                'Our Price ($/MWh)': '${:,.2f}',
                'Avoided Cost Price ($/MWh)': '${:,.2f}',
                'Revenue ($)': lambda x: format_hover_value(x),
                'Operating Expenses ($)': lambda x: format_hover_value(x),
                'EBITDA ($)': lambda x: format_hover_value(x),
                'Total Cash Flows ($)': lambda x: format_hover_value(x),
                'Savings Unlocked ($)': lambda x: format_hover_value(x),
            }))



            # Calculate and display metrics
            total_revenue = revenue_df.loc[revenue_df['Year'] == 'Total', 'Revenue ($)'].values[0]
            total_operating_expenses = revenue_df.loc[revenue_df['Year'] == 'Total', 'Operating Expenses ($)'].values[0]
            total_ebitda = revenue_df.loc[revenue_df['Year'] == 'Total', 'EBITDA ($)'].values[0]
            total_cash_flows = revenue_df.loc[revenue_df['Year'] == 'Total', 'Total Cash Flows ($)'].values[0]
            total_capex = calculate_capex(project_data)

            st.subheader("Key Metrics")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total CapEx", f"${total_capex / 1e6:,.0f}MM")
            with col2:
                st.metric("Total Operating Expenses", f"${total_operating_expenses / 1e6:,.0f}MM")
            with col3:
                cumulative_cash_flows = np.cumsum(cash_flows)
                payback_years = np.argmax(cumulative_cash_flows > 0)
            # Display Total Savings in Key Metrics
            # Calculate total savings
            total_savings_unlocked = revenue_df.loc[revenue_df['Year'] != 'Total', 'Savings Unlocked ($)'].sum()
            

            st.metric("Payback Period", f"{payback_years} years")


            st.subheader("Total Project Metrics")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Revenue", f"${total_revenue / 1e6:,.0f}MM")
            with col2:
                st.metric("Total EBITDA", f"${total_ebitda / 1e6:,.0f}MM")
            with col3:
                st.metric("Total Savings Unlocked", f"${total_savings_unlocked / 1e6:,.0f}MM")

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Cash Flows", f"${total_cash_flows / 1e6:,.0f}MM")
            with col2:
                st.metric("Remaining ITC Cash Flows after Buyout", f"${remaining_itc_cash_flows / 1e6:,.0f}MM")
            with col3: 
                st.metric("NPV", f"${NPV / 1e6:,.2f}MM")



            # Plot cash flows
            cash_flow_df = pd.DataFrame({
                'Year': revenue_df['Year'][:-1],  # Exclude 'Total' row for plotting
                'Cash Flow': cash_flows,
                'Cumulative Cash Flow': np.cumsum(cash_flows)
            })
            st.plotly_chart(plot_cash_flows(cash_flow_df))

            # Plot the stacked savings chart
            st.plotly_chart(plot_stacked_savings_chart(revenue_df))
      




    elif authentication_status == False:
        st.error('Username/password is incorrect')

        
    elif authentication_status == None:
        st.warning('Please enter your username and password')
    # Add a spacer to push the footer down
    st.write('\n' * 100)
    add_custom_footer()
        

   
if __name__ == "__main__":
    main()

