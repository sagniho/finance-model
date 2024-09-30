import streamlit as st
import numpy as np
import numpy_financial as npf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import streamlit_authenticator as stauth
from htbuilder import HtmlElement, div, ul, li, br, hr, a, p, i, img, styles, classes, fonts
from htbuilder.units import percent, px
from htbuilder.funcs import rgba, rgb


def image(src_as_string, **style):
    return img(src=src_as_string, style=styles(**style))

def link(link, text, **style):
    return a(_href=link, _target="_blank", style=styles(**style))(text)

def layout(*args):
    style = """
    <style>
      # MainMenu {visibility: hidden;}
      footer {visibility: hidden;}
      .stApp { bottom: 105px; }
    </style>
    """

    style_div = styles(
        position="fixed",
        left=0,
        bottom=0,
        margin=px(0, 0, 0, 0),
        width=percent(100),
        color="black",
        text_align="center",
        height="auto",
        opacity=1
    )

    style_hr = styles(
        display="block",
        margin=px(4, 4, "auto", "auto"),
        border_style="inset",
        border_width=px(1)
    )

    body = p()
    foot = div(
        style=style_div
    )(
        hr(
            style=style_hr
        ),
        body
    )

    st.markdown(style, unsafe_allow_html=True)

    for arg in args:
        if isinstance(arg, str):
            body(arg)
        elif isinstance(arg, HtmlElement):
            body(arg)

    st.markdown(str(foot), unsafe_allow_html=True)

def footer():
    myargs = [
        i("© Aggreko Energy Transition Solutions 2024"),
        br(),
        link("https://aggrekoets.com/", "aggrekoets.com"),
    ]
    layout(*myargs)


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
    },
    'NJ': {
        'years': list(range(2024, 2071)),
        'prices': [58 + i * 0.35 for i in range(47)]  # Sample escalating prices
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
    if year <= project_data['ppa_tenor']:
        # PPA price starts at initial rate and escalates annually
        price = project_data['ppa_rate'] * (1 + project_data['ppa_escalation']) ** (year - 1)
    else:
        # Use merchant price from the selected state's price curve
        merchant_year = project_data['construction_start'].year + year - 1
        try:
            index = merchant_price_curves[state]['years'].index(merchant_year)
            price = merchant_price_curves[state]['prices'][index]
        except ValueError:
            # If the year is not in the merchant price curve, use the last available price
            price = merchant_price_curves[state]['prices'][-1]
    
    # Get REC price based on the year
    if year >= 1:
        if 1 <= year <= 5:
            rec_price = project_data['rec_price_years_1_5']
        elif 6 <= year <= 10:
            rec_price = project_data['rec_price_years_6_10']
        elif 11 <= year <= 15:
            rec_price = project_data['rec_price_years_11_15']
        else:
            rec_price = 0  # No REC revenue after year 15
    else:
        rec_price = 0  # No production in construction year

    total_price = price + rec_price
    revenue = net_production * total_price / 1000  # Convert to MWh

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
            rec_price = 0
            total_price = 0
            avoided_price = 0
            revenue_type = 'Construction'
            savings = 0
            opex = calculate_operating_expenses(project_data, year, rent_option)
            EBITDA = -opex
            total_cash_flow = EBITDA - capex + tax_equity['fmv']
        else:
            net_production = calculate_annual_production(project_data, year)

            # Determine base price (PPA or Merchant)
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

            # Get REC price based on the year
            if 1 <= year <= 5:
                rec_price = project_data['rec_price_years_1_5']
            elif 6 <= year <= 10:
                rec_price = project_data['rec_price_years_6_10']
            elif 11 <= year <= 15:
                rec_price = project_data['rec_price_years_11_15']
            else:
                rec_price = 0  # No REC revenue after year 15

            # Adjust revenue type if REC is included
            if rec_price > 0:
                revenue_type += ' + REC'

            # Total price including REC
            total_price = price + rec_price

            # Revenue calculation
            revenue = net_production * total_price / 1000  # Convert kWh to MWh

            # Operating Expenses
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
            total_cash_flow = EBITDA - capex_year + tax_equity_cash_flow

            # Savings calculation (excluding REC price)
            savings = (avoided_price - price) * net_production / 1000

        data.append({
            'Year': current_year,
            'Net Production (MWh)': net_production / 1000 if year > 0 else 0,
            'Our Price ($/MWh)': total_price if year > 0 else 0,
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

def main():
    st.set_page_config(page_title='C&I PPA Model', page_icon='a.png', layout='wide')
    col1, col2, col3 = st.columns(3)
    with col1:
        st.header('C&I PPA Model')
    with col3:
        st.image('logo.png', width=150)

    
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
        if username == admin_username:
            user_type = 'admin'
        else:
            user_type = 'user'
            

        st.sidebar.header('Project Inputs')
        with st.sidebar.expander("Project Specifications", expanded=True):
            # Inputs always enabled for this section

            # Project Size Inputs
            project_size_dc = st.number_input(
                'Project Size (MW-dc)',
                value=7.5,
                min_value=0.1,
                disabled=False,
                help='Enter the DC size of the project in megawatts.'
            )
            project_size_ac = st.number_input(
                'Project Size (MW-ac)',
                value=5.0,
                min_value=0.1,
                disabled=False,
                help='Enter the AC size of the project in megawatts.'
            )
            state = st.selectbox(
                'Select State',
                ['NY', 'CA', 'IL', 'TX'],
                help='Select the state where the project is located.'
            )
            # PPA Inputs
            ppa_tenor = st.number_input(
                'PPA Tenor (years)',
                value=20,
                min_value=1,
                max_value=30,
                disabled=False,
                help='Enter the duration of the Power Purchase Agreement in years.'
            )
            post_ppa_tenor = st.number_input(
                'Post-PPA Tenor (years)',
                value=16,
                min_value=0,
                max_value=30,
                disabled=False,
                help='Enter the number of years after the PPA term.'
            )
            ppa_rate = st.number_input(
                'Initial PPA Rate ($/MWh)',
                value=114.05,
                min_value=0.0,
                disabled=False,
                help='Enter the starting price per MWh for the PPA.'
            )
            ppa_escalation = st.number_input(
                'PPA Escalation (%)',
                value=2.0,
                min_value=0.0,
                max_value=10.0,
                disabled=False,
                help='Enter the annual escalation rate for the PPA price.'
            ) / 100
            itc_amount = st.number_input(
                'ITC Amount (%)',
                value=30.0,
                min_value=0.0,
                max_value=100.0,
                disabled=False,
                help='Enter the Investment Tax Credit percentage available for the project.'
            ) / 100
            avoided_cost_ppa_price = st.number_input(
                'Avoided PPA Price ($/MWh)',
                value=155.0,
                min_value=0.0,
                disabled=False,
                help='Enter the avoided cost price per MWh during the PPA term.'
            )
            avoided_cost_escalation = st.number_input(
                'Avoided Cost Escalation (%)',
                value=2.0,
                min_value=0.0,
                max_value=10.0,
                disabled=False,
                help='Enter the annual escalation rate for the avoided cost price.'
            ) / 100
            discount_rate = st.number_input(
                'Discount Rate for NPV and LCOE (%)',
                value=8.0,
                min_value=0.0,
                max_value=100.0,
                disabled=False,
                help='Enter the discount rate used for NPV and LCOE calculations.'
            ) / 100
            production_yield = st.number_input(
                'Production Yield (kWh/kWp)',
                value=1350,
                min_value=500,
                max_value=2500,
                disabled=False,
                help='Enter the annual energy production per kWp installed capacity.'
            )
            # REC Price Inputs
            rec_price_years_1_5 = st.number_input(
                'REC Price ($/MWh) for Years 1-5',
                value=20.0,
                min_value=0.0,
                disabled=False,
                help='Enter the REC price per MWh for years 1 to 5.'
            )
            rec_price_years_6_10 = st.number_input(
                'REC Price ($/MWh) for Years 6-10',
                value=15.0,
                min_value=0.0,
                disabled=False,
                help='Enter the REC price per MWh for years 6 to 10.'
            )
            rec_price_years_11_15 = st.number_input(
                'REC Price ($/MWh) for Years 11-15',
                value=10.0,
                min_value=0.0,
                disabled=False,
                help='Enter the REC price per MWh for years 11 to 15.'
            )

            # Rent option toggle
            rent_option = st.radio(
                "Select Rent Calculation Method",
                options=["Flat Lease/Year", "$/Acre + Escalation", "$/MW-ac + Escalation"],
                index=0,
                help='Choose the method for calculating land rent.'
            )

            # Initialize site_acres to a default value
            site_acres = 0

            # Construction Rent inputs based on the selected rent option
            if rent_option == "Flat Lease/Year":
                construction_rent = st.number_input(
                    'Construction Rent (Flat $/year)',
                    value=50000.0,
                    min_value=0.0,
                    disabled=False,
                    help='Enter the flat construction rent per year.'
                )
                operating_rent = st.number_input(
                    'Operating Rent (Flat $/year)',
                    value=36000.0,
                    min_value=0.0,
                    disabled=False,
                    help='Enter the flat operating rent per year.'
                )
                rent_escalation = st.number_input(
                    'Flat Lease Escalation (%)',
                    value=2.0,
                    min_value=0.0,
                    max_value=10.0,
                    disabled=False,
                    help='Enter the annual escalation rate for flat lease.'
                ) / 100

            elif rent_option == "$/Acre + Escalation":
                construction_rent = st.number_input(
                    'Construction Rent ($/acre/year)',
                    value=600.0,
                    min_value=0.0,
                    disabled=False,
                    help='Enter the construction rent per acre per year.'
                )
                operating_rent = st.number_input(
                    'Operating Rent ($/acre/year)',
                    value=1200.0,
                    min_value=0.0,
                    disabled=False,
                    help='Enter the operating rent per acre per year.'
                )
                rent_escalation = st.number_input(
                    'Rent Escalation (%)',
                    value=2.0,
                    min_value=0.0,
                    max_value=10.0,
                    disabled=False,
                    help='Enter the annual escalation rate for rent per acre.'
                ) / 100
                site_acres = st.number_input(
                    'Site Acres',
                    value=30.0,
                    min_value=0.1,
                    disabled=False,
                    help='Enter the total site area in acres.'
                )

            elif rent_option == "$/MW-ac + Escalation":
                construction_rent = st.number_input(
                    'Construction Rent ($/MW-ac/year)',
                    value=8000.0,
                    min_value=0.0,
                    disabled=False,
                    help='Enter the construction rent per MW-ac per year.'
                )
                operating_rent = st.number_input(
                    'Operating Rent ($/MW-ac/year)',
                    value=25000.0,
                    min_value=0.0,
                    disabled=False,
                    help='Enter the operating rent per MW-ac per year.'
                )
                rent_escalation = st.number_input(
                    'MW-ac Rent Escalation (%)',
                    value=2.0,
                    min_value=0.0,
                    max_value=10.0,
                    disabled=False,
                    help='Enter the annual escalation rate for rent per MW-ac.'
                ) / 100

        with st.sidebar.expander("Schedule", expanded=True):
            cod_date = st.date_input(
                'Commercial Operation Date',
                value=datetime(2025, 12, 31),
                disabled=False,
                help='Select the expected Commercial Operation Date (COD).'
            )
            construction_start = st.date_input(
                'Construction Start',
                value=datetime(2024, 12, 31),
                disabled=False,
                help='Select the expected construction start date.'
            )

        # For other sections, inputs are disabled for 'user' type
        disabled_input = (user_type == 'user')

        with st.sidebar.expander("OpEx Inputs", expanded=False):
            # Operating Expenses Inputs
            opex_escalation = st.number_input(
                'OpEx Escalation (%)',
                value=2.0,
                min_value=0.0,
                max_value=10.0,
                disabled=disabled_input,
                help='Enter the annual escalation rate for operating expenses.'
            ) / 100
            om_cost = st.number_input(
                'O&M Cost ($/kW/year)',
                value=6.00,
                min_value=0.0,
                disabled=disabled_input,
                help='Enter the annual Operations & Maintenance cost per kW.'
            )
            om_escalation = st.number_input(
                'O&M Escalation (%)',
                value=2.0,
                min_value=0.0,
                max_value=10.0,
                disabled=disabled_input,
                help='Enter the annual escalation rate for O&M costs.'
            ) / 100
            asset_management_cost = st.number_input(
                'Asset Management Cost ($/kW/year)',
                value=2.00,
                min_value=0.0,
                disabled=disabled_input,
                help='Enter the annual asset management cost per kW.'
            )
            asset_management_escalation = st.number_input(
                'Asset Management Escalation (%)',
                value=1.5,
                min_value=0.0,
                max_value=10.0,
                disabled=disabled_input,
                help='Enter the annual escalation rate for asset management costs.'
            ) / 100
            insurance_cost = st.number_input(
                'Insurance Cost ($/kW/year)',
                value=4.50,
                min_value=0.0,
                disabled=disabled_input,
                help='Enter the annual insurance cost per kW.'
            )
            property_tax = st.number_input(
                'Property Tax ($/acre/year)',
                value=1200.00,
                min_value=0.0,
                disabled=disabled_input,
                help='Enter the annual property tax per acre.'
            )
            property_tax_escalation = st.number_input(
                'Property Tax Escalation (%)',
                value=2.0,
                min_value=0.0,
                max_value=10.0,
                disabled=disabled_input,
                help='Enter the annual escalation rate for property taxes.'
            ) / 100
            other_asset_management_cost = st.number_input(
                'Other Asset Management Cost ($/kW/year)',
                value=5.00,
                min_value=0.0,
                disabled=disabled_input,
                help='Enter any other annual asset management costs per kW.'
            )
            other_asset_management_escalation = st.number_input(
                'Other Asset Management Escalation (%)',
                value=2.0,
                min_value=0.0,
                max_value=10.0,
                disabled=disabled_input,
                help='Enter the annual escalation rate for other asset management costs.'
            ) / 100
            inverter_replacement_cost = st.number_input(
                'Inverter Replacement Cost ($/kW/year)',
                value=4.00,
                min_value=0.0,
                disabled=disabled_input,
                help='Enter the annual cost for inverter replacements per kW.'
            )
            tax_rate = st.number_input(
                'Tax Rate (%)',
                value=21.0,
                min_value=0.0,
                max_value=100.0,
                disabled=disabled_input,
                help='Enter the applicable tax rate.'
            ) / 100
            developer_fee = st.number_input(
                'Developer Fee ($/W-dc)',
                value=0.25,
                min_value=0.0,
                max_value=1.0,
                disabled=disabled_input,
                help='Enter the developer fee per W-dc.'
            )

        with st.sidebar.expander("CapEx Inputs", expanded=False):
            # Capital Expenditure Inputs
            epc_cost = st.number_input(
                'EPC Cost ($/W-dc)',
                value=1.65,
                min_value=0.0,
                max_value=5.0,
                disabled=disabled_input,
                help='Enter the Engineering, Procurement, and Construction cost per W-dc.'
            )
            interconnection_cost = st.number_input(
                'Interconnection Cost ($/W-dc)',
                value=0.10,
                min_value=0.0,
                max_value=1.0,
                disabled=disabled_input,
                help='Enter the interconnection cost per W-dc.'
            )
            transaction_costs = st.number_input(
                'Transaction Costs ($/W-dc)',
                value=0.07,
                min_value=0.0,
                max_value=1.0,
                disabled=disabled_input,
                help='Enter any additional transaction costs per W-dc.'
            )

        with st.sidebar.expander("Tax Equity Inputs", expanded=False):
            # Tax Equity Financing Inputs
            itc_eligible_portion = st.number_input(
                'ITC-Eligible Portion (%)',
                value=95.0,
                min_value=0.0,
                max_value=100.0,
                disabled=disabled_input,
                help='Enter the percentage of CapEx that is eligible for ITC.'
            ) / 100
            fmv_step_up = st.number_input(
                'FMV Step-up (%)',
                value=30.0,
                min_value=0.0,
                max_value=100.0,
                disabled=disabled_input,
                help='Enter the percentage increase in Fair Market Value (FMV) due to step-up.'
            ) / 100
            te_investment = st.number_input(
                'TE Investment ($ of ITC)',
                value=1.15,
                min_value=0.0,
                max_value=5.0,
                disabled=disabled_input,
                help='Enter the amount of Tax Equity Investment per dollar of ITC.'
            )
            preferred_return = st.number_input(
                'Preferred Return (%)',
                value=2.5,
                min_value=0.0,
                max_value=20.0,
                disabled=disabled_input,
                help='Enter the preferred return rate for tax equity investors.'
            ) / 100
            buyout_year = st.number_input(
                'Buyout Year',
                value=7,
                min_value=1,
                max_value=20,
                disabled=disabled_input,
                help='Enter the year in which the buyout option is exercised.'
            )
            buyout_percentage = st.number_input(
                'Buyout (%)',
                value=7.25,
                min_value=0.0,
                max_value=100.0,
                disabled=disabled_input,
                help='Enter the percentage of FMV for the buyout price.'
            ) / 100

        with st.sidebar.expander("Other Parameters", expanded=False):
            # Additional Parameters
            degradation_rate = st.number_input(
                'Annual Degradation Rate (%)',
                value=0.5,
                min_value=0.0,
                max_value=5.0,
                disabled=disabled_input,
                help='Enter the annual degradation rate of the solar panels.'
            ) / 100
            degradation_start_year = st.number_input(
                'Degradation Start Year',
                value=1,
                min_value=1,
                disabled=disabled_input,
                help='Enter the year when degradation starts.'
            )
            ppa_escalation_start_year = st.number_input(
                'PPA Escalation Start Year',
                value=2,
                min_value=1,
                disabled=disabled_input,
                help='Enter the year when PPA price escalation starts.'
            )

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
            'state': state,
            'rec_price_years_1_5': rec_price_years_1_5,
            'rec_price_years_6_10': rec_price_years_6_10,
            'rec_price_years_11_15': rec_price_years_11_15
        }

        if st.button('Calculate IRR'):
            # Step 1: Calculate Cash Flows and IRR
            cash_flows, remaining_itc_cash_flows = calculate_cash_flows(project_data, rent_option, state)
            irr = calculate_irr(cash_flows)
            st.success(f'The project Unlevered IRR is: {irr*100:.2f}%')
            
            # Step 2: Generate Revenue Table
            revenue_df = generate_revenue_table(project_data, rent_option, state)

            # Step 3: Calculate NPV
            NPV = npf.npv(discount_rate, cash_flows)
            
            # Step 4: Calculate Unlevered CapEx
            total_capex = calculate_capex(project_data)
            tax_equity = calculate_tax_equity(project_data)
            tax_equity_fmv = tax_equity['fmv']
            unlevered_capex = total_capex - tax_equity_fmv

            # Step 5: Calculate Saved NPV (Assuming Saved NPV is NPV without Tax Equity minus NPV with Tax Equity)
            # To calculate NPV without Tax Equity, we need to adjust cash flows
            # Assuming that Tax Equity affects only the initial cash flow (Year 0)
            # Hence, we subtract tax_equity['fmv'] from Year 0 cash flow
            cash_flows_no_tax = cash_flows.copy()
            cash_flows_no_tax[0] += tax_equity_fmv  # Remove the effect of Tax Equity FMV
            NPV_no_tax = npf.npv(discount_rate, cash_flows_no_tax)
            saved_NPV = NPV_no_tax - NPV

            # Step 6: Calculate Savings Notional
            savings_notional = revenue_df.loc[revenue_df['Year'] != 'Total', 'Savings Unlocked ($)'].sum()

            # Step 7: Calculate Payback Period
            cumulative_cash_flows = np.cumsum(cash_flows)
            payback_years = next((year for year, cum_cf in enumerate(cumulative_cash_flows) if cum_cf > 0), 'Not achieved')

            # Step 8: Calculate Additional Metrics if needed
            # (If 'Saved NPV' has a different definition, adjust accordingly)

            # Display Key Metrics
            
            st.subheader("Key Metrics")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Unlevered IRR", f"{irr*100:.2f}%", help='Internal Rate of Return without considering debt financing.')
            with col2:
                total_revenue = revenue_df.loc[revenue_df['Year'] == 'Total', 'Revenue ($)'].values[0]
                st.metric("Total Revenue", f"${total_revenue / 1e6:,.2f}MM", help='Total revenue over the project lifetime.')
            with col3:
                total_ebitda = revenue_df.loc[revenue_df['Year'] == 'Total', 'EBITDA ($)'].values[0]
                st.metric("Total EBITDA", f"${total_ebitda / 1e6:,.2f}MM", help='Earnings Before Interest, Taxes, Depreciation, and Amortization over the project lifetime.')
            with col4:
                st.metric("Unlevered CapEx", f"${unlevered_capex / 1e6:,.2f}MM", help='Total capital expenditure minus tax equity FMV.')

            col5, col6, col7, col8 = st.columns(4)
            with col5:
                st.metric("NPV", f"${NPV / 1e6:,.2f}MM", help='Net Present Value of the project.')
            with col6:
                st.metric("Saved NPV", f"${saved_NPV / 1e6:,.2f}MM", help='Increase in NPV due to tax equity financing.')
            with col7:
                st.metric("Savings Notional", f"${savings_notional / 1e6:,.2f}MM", help='Total savings unlocked for the customer.')
            with col8:
                st.metric("Payback Period", f"{payback_years} years", help='Number of years to recover the initial investment.')

            st.divider()


             # Step 12: Display Revenue Table at the Bottom
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


           
            # Step 10: Plot Cash Flows
            cash_flow_df = pd.DataFrame({
                'Year': revenue_df['Year'][:-1],  # Exclude 'Total' row for plotting
                'Cash Flow': cash_flows,
                'Cumulative Cash Flow': np.cumsum(cash_flows)
            })
            st.plotly_chart(plot_cash_flows(cash_flow_df))

            # Step 11: Plot Stacked Savings Chart
            st.plotly_chart(plot_stacked_savings_chart(revenue_df))

           
            # Optional: Provide a download button for the revenue table
            csv = revenue_df.to_csv(index=False)
            st.download_button(
                label="Download Revenue Table as CSV",
                data=csv,
                file_name='revenue_table.csv',
                mime='text/csv',
            )

    elif authentication_status == False:
        st.error('Username/password is incorrect')

        
    elif authentication_status == None:
        st.warning('Please enter your username and password')

    footer()

   
if __name__ == "__main__":
    main()
