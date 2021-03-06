# -*- coding: utf-8 -*-
"""
Created on Sat Aug 29 11:29:34 2020

@author: Pavan
"""

import pandas as pd
pd.set_option('mode.chained_assignment', None)
import numpy as np
import math
import matplotlib  as mpl
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
mpl.rcParams['font.family'] = 'serif'
import scipy.stats as stats
import itertools
from datetime import datetime, date
import os
import yfinance as yf
# from functools import partial
from american_option_pricing import american_option
import density_utilities as du
import prediction_ensemble_py as pe
import multi_step_final_v1 as ms
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

"""
#######################################################################################
                                      Import Data                     
#######################################################################################
"""

data = pd.read_excel('etfs_nov_20.xlsx', index_col=None)  
current_date = date(2020,11,14)
expiry_date = date(2020,11,20)
days_to_expiry = np.busday_count( current_date, expiry_date)+1



# min_p_profit = 35
# hor_leg_factor = 0.05


forecast_dens = False
save_results = True
save_plots = True
calculate_strategies = False


#Strategies = ["Butterfly","Bear Double Broken Wing Butterfly","Bull Double Broken Wing Butterfly", "Iron Condor"]
Strategies = ["Bear Double Broken Wing Butterfly","Bull Double Broken Wing Butterfly", "Iron Condor"]

"""
#######################################################################################
                                    Get Risk Free Date                   
#######################################################################################
"""

print("\n Gathering Risk Free Rate")

rf_eod_data = yf.download("^IRX", start="2020-07-01", end= current_date.strftime("%Y-%m-%d"))

for col in rf_eod_data.columns:
    rf_eod_data[col] = pd.to_numeric(rf_eod_data[col],errors='coerce')

rf_eod_data=rf_eod_data.fillna(method='ffill')

rf_eod_data['interest']=((1+(rf_eod_data['Adj Close']/100))**(1/252))-1

rf_eod_data['annualized_interest']=252*(((1+(rf_eod_data['Adj Close']/100))**(1/252))-1)

rf_value =rf_eod_data['annualized_interest'].iloc[-1]
print("\nCurrent Risk Free Rate is :",'{:.3f}%'.format(rf_value*100))


"""
#######################################################################################
                                    Data Cleaning                    
#######################################################################################
"""



def wrang_1(df, col_names):
    for col in col_names:
 
        df[col] = df[col].str.rstrip('%')
        df[col] = pd.to_numeric(df[col],errors='coerce')
        df[col] = [float(x)/100.0 for x in df[col].values]
    return df

convert_cols = ["Impl Vol", "Prob.ITM","Prob.OTM","Prob.Touch"]
data = wrang_1(data,convert_cols)

def label_type(row):
   if row['Symbol'][0] == "." :
      return 'Option'
   return 'Stock'
data['Type']=data.apply(lambda row: label_type(row), axis=1)

data['Expiry_Date']= data.Symbol.str.extract('(\d+)')
data['Expiry_Date'] = data['Expiry_Date'].apply(lambda x: pd.to_datetime(str(x), format='%y%m%d'))
expiry_date_str = expiry_date.strftime("%Y%m%d")
data['Expiry_Date'] = data['Expiry_Date'].fillna(pd.Timestamp(expiry_date_str))
data['Expiry_Date'] = data['Expiry_Date'].apply(lambda x: x.strftime('%Y_%m_%d'))

#TODO: Change the logic for new symbol. Works only for this year. 
data['Group']= data.Symbol.apply(lambda st: st[st.find(".")+1:st.find("20")])

data['Group'] = np.where(data['Type'] == "Stock", data['Symbol'],data['Group']) 

data['Chain_ID'] = data['Group']+"_"+data['Expiry_Date']

data['Spread'] = data['Bid']-data['Ask']


stock_data = data[data['Type'] == "Stock"]
stock_data.rename(columns={"Description": "stock_Description", 
                           "Last": "stock_Last",
                           "High":"stock_High",
                           "Low":"stock_Low",
                           "Open" : "stock_Open",
                           "Volume":"stock_Volume",
                           "Bid":"stock_Bid",
                           "Ask":"stock_Ask",
                           "Impl Vol":"stock_Impl_Vol",
                           "Spread":"stock_Spread"}, inplace=True)    
stock_data = stock_data[["stock_Description","stock_Last","stock_High","stock_Low",
                         "stock_Open","stock_Volume","stock_Bid","stock_Ask",
                         "stock_Impl_Vol","stock_Spread","Chain_ID"]]
# stock_data['Chain_ID'] = 'SPXW_2020_10_07'
    
option_data = data[data['Type']=="Option"]
option_data['Option_type'] = option_data.loc[:,'Description'].str.split(' ').str[-1]

final_dataset = pd.merge(option_data,stock_data,on=['Chain_ID'])



"""
#######################################################################################
                                    Option Chain Class                   
#######################################################################################
"""


class Option_chain(object):
    
    def __init__(self,asset,final_dataset):
        self.Name = asset
        self.lot_size = 100
        
        setattr(self,"Time_to_exp", days_to_expiry)
        
        asset_df = final_dataset[final_dataset['Group']==asset]
        
        asset_df["Dummy_Strike"] = asset_df.loc[:,"Strike"]
        
        filtered = asset_df.groupby('Strike')['Strike'].filter(lambda x: len(x) == 2)
        not_common = asset_df[~asset_df['Strike'].isin(filtered)]
        
        records = not_common.to_dict('records')
        
        to_add = list()
        
        for record in records:
            new = record.copy()
            if record["Option_type"] == "CALL":
                for keys,value in new.items():
                    if type(value) ==str :
                        if keys in ["Symbol","Description"]:
                            new[keys] = "Dummy"
                        if keys == "Option_type":
                            new[keys] = "PUT"
                    else:
                        if keys in ["Bid","Ask"]:
                            option_type = 'p'
                            fs = new['stock_Last']
                            x = new['Strike']
                            t=  self.Time_to_exp/252
                            r= rf_value
                            v= new['Impl Vol']
                            new[keys] = american_option(option_type, fs, x, t, r, v)[0]
                        if keys[:5] != "stock" and (keys not in ["Strike", "Dummy_Strike", "Ask","Bid", "Impl Vol"]):
                            new[keys] = 0 
                        
                new["Strike"] = -1000000
                
            else:
                for keys,value in new.items():
                    if type(value) ==str :
                        if keys in ["Symbol","Description"]:
                            new[keys] = "Dummy"
                        if keys == "Option_type":
                            new[keys] = "CALL"
                    else:
                        if keys in ["Bid","Ask"]:
                            option_type = 'p'
                            fs = new['stock_Last']
                            x = new['Strike']
                            t= self.Time_to_exp/252
                            r= rf_value
                            v= new['Impl Vol']
                            new[keys] = american_option(option_type, fs, x, t, r, v)[0]
                        if keys[:5] != "stock" and (keys not in  ["Strike", "Dummy_Strike", "Ask","Bid", "Impl Vol"]):
                            new[keys] = 0 
                            
                new["Strike"] = 1000000
    
            to_add.append(new)
        
        
        df_dummy_options = pd.DataFrame(to_add)
        
        asset_df = asset_df.append(df_dummy_options)
        
        asset_df = asset_df.sort_values(by=['Option_type', 'Dummy_Strike'])
        
        greeks = ["Delta","Gamma","Theta","Vega","Rho"]
        for greek in greeks:
            setattr(self,"Var_"+greek, np.std(asset_df[greek].values))
        
        


        
        self.call_df = asset_df[asset_df['Option_type']=="CALL"]
        self.put_df = asset_df[asset_df['Option_type']=="PUT"]
        
        
        cols = ["Bid","Ask", "Last", "Delta","Gamma","Theta","Vega","Rho","Impl Vol","Strike", "Dummy_Strike"]
        
        for col in cols:
            setattr(self,"Call_"+col,self.call_df[col].values)
            setattr(self,"Put_"+col,self.put_df[col].values)
            
            
        setattr(self,"Call_total", len(self.Call_Strike))
        setattr(self,"Put_total", len(self.Put_Strike))
      
        setattr(self,"Stock_Last", asset_df["stock_Last"].iloc[0])
        setattr(self,"Stock_Volume", asset_df["stock_Volume"].iloc[0])
        
        setattr(self,"Description", asset_df["stock_Description"].iloc[0])
        
        setattr(self,"Stock_Volt", asset_df["stock_Impl_Vol"].iloc[0])

        
        
        
        
        
        std = self.Stock_Last*(self.Stock_Volt*((self.Time_to_exp/252)**0.5))
        self.sigma = std
        
        self.Rf = rf_value
        
        vol_day = (self.Stock_Volt)*math.sqrt(1/252)
        
        ln_S_0 = math.log(self.Stock_Last)
        rt = self.Rf*(self.Time_to_exp/252)
        s_term= -0.5*(vol_day**2)*(self.Time_to_exp)
        
        mu_n = ln_S_0+rt+s_term
        sigma_n = vol_day*math.sqrt(self.Time_to_exp)
        
        
        
        s = sigma_n
        
        scale = math.exp(mu_n)
        
        self.lognormal_s = s
        self.lognormal_scale =scale
        
        
        
        S=self.Stock_Last
        
        #self.S_space = np.linspace(self.Stock_Last - 4*self.sigma, self.Stock_Last + 4*self.sigma, 20)
        self.S_space = np.arange(S-0.5*S,S+0.5*S,0.1)
        self.S_density = stats.lognorm.pdf(self.S_space,s,loc=0,scale=scale)
       
        
        
        
        
        
        
        ## for optimization 
        variables = ["Ask","Bid","Strike","Delta","Gamma","Theta","Vega","Rho"]
        for variable in variables:
            cal_cont = getattr(self,"Call_"+variable)
            put_cont = getattr(self,"Put_"+variable)
            array = np.hstack((cal_cont[:,np.newaxis],put_cont[:,np.newaxis]))
            setattr(self, variable+"_List" , [[ array[i,j] for j in range(array.shape[1])] for i in range(array.shape[0])])
        

"""
#######################################################################################
                                    Create list of Options Chains               
#######################################################################################
""" 

now = datetime.now()
path = "./"+now.strftime("%Y_%m_%d_%H_%M_%S")

try:
    os.mkdir(path)
except OSError:
    print ("\n Creation of the directory %s failed" % path)
else:
    print ("\n Successfully created the directory %s " % path)

Assets = list(final_dataset['Group'].unique())


All_Option_Chains = list()

predictions = list()
predictions_vol = list()
dens_results = list() 
forecast_results_l = list()

for i in range(len(Assets)): 
    print("\n Pre-Processing ",i+1,"/",len(Assets), "-", Assets[i])

    opt_chain = Option_chain(Assets[i],final_dataset)
    All_Option_Chains.append(opt_chain)
    
    prices = opt_chain.S_space
    logn_dens = opt_chain.S_density
    if forecast_dens:
        print("\t Forecasting Real World Density function ")
        res_dict, prices, risk_neutral, real_world_1, real_world_2 = du.calculate_densities(opt_chain)
        dens_results.append(res_dict)
        opt_chain.dens_results = res_dict
        opt_chain.S_space_1 = prices
        opt_chain.S_density_0 = risk_neutral
        opt_chain.S_density_1 = real_world_1
        opt_chain.S_density_2 = real_world_2
        opt_chain.dens_to_use = real_world_1
    else:
        opt_chain.dens_to_use = logn_dens
        
        
    print("\t Forecasting Close price using time series ensembles ")
    res_pred, result_forecast = ms.multi_step_pred(Assets[i],current_date.strftime("%Y-%m-%d"),path, Assets[i]+'_pred',save_plots)
    opt_chain.forecast_data = res_pred
    opt_chain.ret_forecast = result_forecast
    
    print("\t Forecasting Volatility ATR(14) using time series ensembles ")    
    res_pred_vol, result_forecast_vol = ms.multi_step_pred_vol(Assets[i],current_date.strftime("%Y-%m-%d"),path, Assets[i]+'_pred',save_plots)
    opt_chain.forecast_data_vol = res_pred_vol
    opt_chain.ret_forecast_vol = result_forecast_vol
    
    f_results = dict()

    f_results['Description'] = opt_chain.Description
    f_results['Asset'] = Assets[i]
    f_results['Last'] = opt_chain.Stock_Last
    f_results['Volume'] = opt_chain.Stock_Volume
    
    rows = len(result_forecast)
    for k  in range(rows):
        a = round(result_forecast.loc[k,'log_ret']*100,2)
        print("\t Predicted Return for ", k+1, " day :", a," %")
    
    for k  in range(rows):
        a = round(result_forecast.loc[k,'cum_ret']*100,2)
        b = round(result_forecast.loc[k,'yhat_lower'],2)
        c = round(result_forecast.loc[k,'yhat_upper'],2)
        print("\t Predicted Cum Return for ", k+1, " day :", a, "%.  95 % Bounds are(",b, ", ", c , ')')
        if k==rows-1:
            f_results['5d Cum Return'] = a
            f_results['predicted price'] = (1+(a/100))*opt_chain.Stock_Last
        
        
    rows = len(result_forecast_vol)
    for k  in range(rows):
        a = round(result_forecast_vol.loc[k,'log_ret']*100,2)
        print("\t Predicted vol change for ", k+1, " day :", a," %")
    
    for k  in range(rows):
        a = round(result_forecast_vol.loc[k,'cum_ret']*100,2)
        b = round(result_forecast_vol.loc[k,'yhat_lower'],2)
        c = round(result_forecast_vol.loc[k,'yhat_upper'],2)
        print("\t Predicted vol for ", k+1, " day :", a, "%.  95 % Bounds are(",b, ", ", c , ')')
        if k==rows-1:
            f_results['5d ATR(14) change'] = a    
    
    f_results['Implied Volatility'] = 100*opt_chain.Stock_Volt
    
    forecast_results_l.append(f_results)
    
    res_pred['Description'] = opt_chain.Description
    predictions.append(res_pred)
    predictions_vol.append(res_pred_vol)


    
    if save_plots == True:
        if forecast_dens:
            du.plot_densities(opt_chain.Stock_Last,opt_chain.Name+'_dens',path, prices,risk_neutral, real_world_1, real_world_2, logn_dens)
        else:
            du.plot_densities_2(opt_chain.Stock_Last,opt_chain.Name+'_dens',path, prices, logn_dens)
        # pe.plot_actual_pred(act.iloc[-50:], pred, path, Assets[i]+'_pred')

forecast_results_df = pd.DataFrame(forecast_results_l)
predname = os.path.join(path, "00_Forecast_results.xlsx")   
forecast_results_df.to_excel(predname,index=False)

if forecast_dens ==True:
    density_results = pd.DataFrame(dens_results)
    densname = os.path.join(path, "02_density_results.xlsx")   
    density_results.to_excel(densname,index=False)


        

        
"""
#######################################################################################
                                    Strategy Class                
#######################################################################################
""" 



class Strategy(object):
    
    def __init__(self,allocation,chain,name):
        self.Option_Chain = chain
        
        call_alloc = allocation[:,0]
        put_alloc = allocation[:,-1]
        
        call_alloc[chain.Call_Strike==1000000] = 0
        put_alloc[chain.Put_Strike==-1000000] = 0
        
        self.Call_allocation = call_alloc
        self.Put_allocation =  put_alloc
        
        self.loss_threshold = 1000
        
        self.dens_to_use = chain.dens_to_use
        self.vec_final_pnl = np.vectorize(self.final_pnl)
        self.e_pnl = self.expected_pnl() 
#        self.e_utility = self.expected_utility()
        self.pnl_space = self.pnl_space()
        self.Max_Profit = max(self.pnl_space)
        self.Max_Loss = -1*(min(self.pnl_space))
        self.sigma = self.Option_Chain.sigma


        self.name = name
        self.Prob_profit = self.prob_profit()
        self.Prob_loss = self.prob_loss()
        
        Greeks = ["Delta","Gamma","Theta","Vega","Rho"]
        for greek in Greeks:
            call_att = getattr(self.Option_Chain, "Call_"+greek)
            put_att = getattr(self.Option_Chain, "Put_"+greek)
            call_c = self.Option_Chain.lot_size*(np.sum(self.Call_allocation*call_att))
            put_c = self.Option_Chain.lot_size*(np.sum(self.Put_allocation*put_att))
            setattr(self,"Strategy_"+greek, call_c+put_c)
        


       
    def payoff(self,S_T):
        call_payoff = self.Option_Chain.lot_size*(np.sum(self.Call_allocation*np.maximum((S_T-self.Option_Chain.Call_Strike),0)))
        put_payoff = self.Option_Chain.lot_size*(np.sum(self.Put_allocation*np.maximum((self.Option_Chain.Put_Strike-S_T),0)))
        final_payoff = call_payoff+put_payoff
        return final_payoff
    
    def initial_cost(self):

        call_cost = self.Option_Chain.Call_Ask*((self.Call_allocation>0).astype(int))+self.Option_Chain.Call_Bid*((self.Call_allocation<=0).astype(int))
        put_cost = self.Option_Chain.Put_Ask*((self.Put_allocation>0).astype(int))+self.Option_Chain.Put_Bid*((self.Put_allocation<=0).astype(int))
        total_call_cost = np.sum(self.Option_Chain.lot_size*(self.Call_allocation*call_cost))
        total_put_cost = np.sum(self.Option_Chain.lot_size*(self.Put_allocation*put_cost))
        return total_call_cost+total_put_cost

    def final_pnl(self,S_T):
        return self.payoff(S_T)-self.initial_cost()
    
    def plot_pnl(self):
#        S = np.linspace(self.Option_Chain.Stock_Last - 4*self.sigma, self.Option_Chain.Stock_Last + 4*self.sigma, 1000)   
        S = self.Option_Chain.S_space
        pnl = self.vec_final_pnl(S)
        max_loss = round(min(pnl),2)
        e_pnl = self.expected_pnl()
        fig,ax = plt.subplots(1, 1, figsize=(9, 5))
        plt.plot(S,pnl,lw=2.5, color='blue', label = "Final PnL as a function of $S_T$")
        plt.axhline(y=0, color="black", lw = 1)
        plt.axhline(y=max_loss, color="red",linestyle='--', lw = 1, label = "Lowest Pnl = {}".format(max_loss))
        plt.axhline(y = e_pnl  , color = "magenta", linestyle='--', lw =1, label = "$E(Profit) : {}$".format(e_pnl) )
        plt.axvline(x = self.Option_Chain.Stock_Last, color="green", linestyle='--', label = "$S_0 : {}$".format(self.Option_Chain.Stock_Last))
        fmt = '${x:,.2f}'
        tick = mtick.StrMethodFormatter(fmt)
        ax.yaxis.set_major_formatter(tick)
        ax.xaxis.set_major_formatter(tick)
        plt.xlabel('$S_T$')
        plt.ylabel('Final P & L ')
        ax.set_axisbelow(True)
        ax.minorticks_on()
        ax.grid(which='major', linestyle='-')
        ax.grid(which='minor', linestyle=':')
        plt.legend()
        plt.grid(True)
        
        ax2 = ax.twinx()
        color = 'tab:red'
        ax2.set_ylabel('Pdf', color=color)  # we already handled the x-label with ax1
        ax2.plot(S, self.dens_to_use, color=color, linestyle='--', lw = 2, label = "Density used")
#        ax2.plot(S, self.Option_Chain.S_density_0, color='tab:red', linestyle='--', lw = 2, label = "Risk Neutral Density of $S_T$")
        ax2.tick_params(axis='y', labelcolor=color)
        self.figure = fig
        
        
    def e_curve(self):
        s_paths = self.Option_Chain.S_space
        s_paths_density = self.dens_to_use
        final_pnl = self.vec_final_pnl(s_paths)
        curve = s_paths_density*final_pnl
        return curve
        
    def utility_curve(self):
        s_paths = self.Option_Chain.S_space
        s_paths_density = self.dens_to_use
        final_pnl = self.vec_final_pnl(s_paths)
        curve = s_paths_density*np.exp(final_pnl)
        return curve
        
    def expected_utility(self):
        curve = self.utility_curve()
        expected_util = (self.Option_Chain.S_space[1]-self.Option_Chain.S_space[0])*(sum(curve)-0.5*curve[0]-0.5*curve[-1])
        return round(expected_util,2)
    
    def expected_pnl(self):
        curve = self.e_curve()
        h = (self.Option_Chain.S_space[1]-self.Option_Chain.S_space[0])
        expected_pnl = h*(sum(curve)-0.5*curve[0]-0.5*curve[-1])
        return round(expected_pnl,2)
    
    def pnl_st(self):
        return self.final_pnl(self.Option_Chain.Stock_Last)
    
    def pnl_space(self):
        return self.vec_final_pnl(self.Option_Chain.S_space)
    
    def prob_profit(self):
        S = self.Option_Chain.S_space
        S_dens = self.dens_to_use
        pnl_curve = self.pnl_space.copy()
        S_dens_pos = S_dens.copy()
        S_dens_pos[pnl_curve<=0] = 0 
        prob_profit = (S[1]-S[0])*(sum(S_dens_pos)- 0.5*S_dens_pos[0]-0.5*S_dens_pos[-1])
        return round(100*prob_profit,2)
    
    def prob_loss(self):
        S = self.Option_Chain.S_space
        S_dens = self.dens_to_use
        pnl_curve = self.pnl_space.copy()
        S_dens_neg = S_dens.copy()
        S_dens_neg[pnl_curve>=0] = 0 
        prob_loss = (S[1]-S[0])*(sum(S_dens_neg)- 0.5*S_dens_neg[0]-0.5*S_dens_neg[-1])
        return round(100*prob_loss, 2)
    
    def summary(self):
        strat_summary = dict()
        
        strat_summary["Underlying"] = self.Option_Chain.Name
        strat_summary["Description"] = self.Option_Chain.Description
        strat_summary["Name"] = self.name
        


        strat_summary["Expected PnL"] = self.e_pnl
#        strat_summary["Expected Utility"] = self.e_utility
        
        strat_summary["Cost of Strategy"] = self.initial_cost()
        # strat_summary["Total Debit"] = (-1*self.initial_cost())+self.Max_Loss
        
        # strat_summary["Leg_profit"] = -1*self.initial_cost()
        strat_summary["Max_Profit"] = self.Max_Profit
        strat_summary["Max_Loss"] = self.Max_Loss
        
        strat_summary["Prob of Profit"] = self.Prob_profit
        strat_summary["Prob of Loss"] = self.Prob_loss
        
        #strat_summary["Exp_Pnl/Max_Loss"]=self.e_pnl/self.Max_Loss
        # strat_summary["Leg_Profit_Factor"] = -1*self.initial_cost()/self.Max_Loss
        strat_summary["Profit_Factor"] = self.Max_Profit/self.Max_Loss #strat_summary["Max_Profit"]/strat_summary["Max_Loss"]
        

        Call_strikes = self.Option_Chain.Call_Strike
        Put_strikes = self.Option_Chain.Put_Strike
        
        k=1
        for i in range(len(Call_strikes)):
            if self.Call_allocation[i]!=0:
                strat_summary["Strike_"+str(k)+"_type"] = "Call"
                strat_summary["Strike_"+str(k)] =  Call_strikes[i]
                strat_summary["Strike_"+str(k)+"_alloc"] = self.Call_allocation[i]
                strat_summary["Strike_"+str(k)+"_index"] = i
                k+=1

        for i in range(len(Put_strikes)):
            if self.Put_allocation[i]!=0:
                strat_summary["Strike_"+str(k)+"_type"] = "Put"
                strat_summary["Strike_"+str(k)] =  Put_strikes[i]
                strat_summary["Strike_"+str(k)+"_alloc"] = self.Put_allocation[i]
                strat_summary["Strike_"+str(k)+"_index"] = i
                k+=1
                
        Greeks = ["Delta","Gamma","Theta","Vega","Rho"]
        
        for greek in Greeks:
            strat_summary["Strategy_"+greek] = getattr(self,"Strategy_"+greek)
            
        S = self.Option_Chain.S_space
        pnl = self.vec_final_pnl(S)
        
        strat_summary["Strategy_left_leg"] = pnl[0]
        strat_summary["Strategy_right_leg"] = pnl[-1]
        
        strat_summary["Total_Strikes"] = k
        

        return strat_summary
    


def combine_strat(call_strat, put_strat,chain):
    allocation = np.zeros((chain.Call_total,2))
    allocation[:,0] = call_strat.Call_allocation + put_strat.Call_allocation

    strategy = Strategy(allocation, chain, "Double Broken Butterfly")
    return strategy

        
        
    
"""
#######################################################################################
                                    Calculations                 
#######################################################################################
""" 


if calculate_strategies == True:
    tic = datetime.now()
    #All_Strategies = list()
    All_Strategies_Summary = list()
    
    Bear_Fly_Summary = list()
    Bull_Fly_Summary = list()
    Fly_Summary = list()
    Iron_Con_Summary = list()
    
    tic = datetime.now()
    
    
    for i in range(len(All_Option_Chains)):
        chain = All_Option_Chains[i]
        print("\n Processing ",i+1,"/",len(All_Option_Chains), "-", chain.Name, " : ", chain.Description)
    
        Master_List_Strategies = list()
        Master_List_Strategy_Summary = pd.DataFrame()
        #if predictions[i]['direction'] in ['Slight Bearish','Bearish']:
        # if predictions[i]['direction'] in ['Slight Bullish','Bullish']:
    
        """
        #######################################################################################
                                            Bull Call Broken Butterfly                 
        #######################################################################################
        """ 
    
        bull_pos = np.empty((0,3))
        bull_call_fly_df = pd.DataFrame()
        if "Bull Double Broken Wing Butterfly" in Strategies:
            Strategy_name = "Bullish Call Modified Butterfly"
            print("\t Processing ", Strategy_name, " Strategy")
            bull_call_fly_strat = list()
            bull_call_fly = list()
    
            call_1_pos = list(np.arange(chain.Call_total))
            call_2_pos = list(np.arange(chain.Call_total))
            call_3_pos = list(np.arange(chain.Call_total))
            call_1_quantity = 10#list(np.arange(1,max_quantity_per_leg+1))
            call_2_quantity = 20#list(np.arange(1,max_quantity_per_leg+1))
            call_3_quantity = 10#list(np.arange(1,max_quantity_per_leg+1))
            
            iterables = [call_1_pos,call_2_pos,call_3_pos]
            
            bull_pos = np.zeros((0,3))
            bull_strike = np.zeros((0,3))
            for t in itertools.product(*iterables):
                pos_1, pos_2, pos_3 = t
                pos_cons = (chain.Call_Strike[pos_2]-chain.Call_Strike[pos_1])>=2*(chain.Call_Strike[pos_3]-chain.Call_Strike[pos_2]) and (chain.Call_Strike[pos_2]-chain.Call_Strike[pos_1])<=9*(chain.Call_Strike[pos_3]-chain.Call_Strike[pos_2])
                if pos_1 < pos_2 and pos_2 < pos_3 and pos_cons:
                    allocation = np.zeros((chain.Call_total,2))
                    allocation[pos_1,0] = call_1_quantity
                    allocation[pos_2,0] = -1*call_2_quantity
                    allocation[pos_3,0] = call_3_quantity
                    strat = Strategy(allocation,chain,Strategy_name)
                    details = strat.summary()
                    if details["Strategy_right_leg"]>0 :
                        bull_call_fly_strat.append(strat)
                        bull_call_fly.append(details)
                        
                        bull_pos = np.vstack((bull_pos,np.array([[pos_1,pos_2,pos_3]])))
                        bull_strike = np.vstack((bull_strike, np.array([[chain.Call_Strike[pos_1], chain.Call_Strike[pos_2], chain.Call_Strike[pos_3]]])))
                
                        
            if len(bull_call_fly)>0:
                bull_call_fly_df = pd.DataFrame(bull_call_fly)
                bull_call_fly_df = bull_call_fly_df.sort_values(by=["Prob of Profit"], ascending=False)
    
                # Master_List_Strategies.append(bull_put_fly_strat)  
                print("\t \t Added ", len(bull_call_fly), " Strategies")
    
        
        """
        #######################################################################################
                                            Bear Call Broken Butterfly                 
        #######################################################################################
        """ 
    
     
        # if predictions[i]['direction'] in ['Slight Bearish','Bearish']:
        #if predictions[i]['direction'] in ['Slight Bullish','Bullish']:    
        bear_call_fly_df = pd.DataFrame()
        if "Bear Double Broken Wing Butterfly" in Strategies:
            Strategy_name = "Bearish Call Modified Butterfly"
            print("\t Processing ", Strategy_name, " Strategy")
            bear_call_fly_strat = list()
            bear_call_fly = list()
    
            call_1_pos = list(np.arange(chain.Call_total))
            call_2_pos = list(np.arange(chain.Call_total))
            call_3_pos = list(np.arange(chain.Call_total))
            call_1_quantity = 10#list(np.arange(1,max_quantity_per_leg+1))
            call_2_quantity = 20#list(np.arange(1,max_quantity_per_leg+1))
            call_3_quantity = 10#list(np.arange(1,max_quantity_per_leg+1))
            
            
            
            
            bear_pos = np.zeros((0,3))
            bear_strike = np.zeros((0,3))
            
            iterables = [call_1_pos,call_2_pos,call_3_pos]
            for t in itertools.product(*iterables):
                pos_1, pos_2, pos_3 = t
                pos_cons = (chain.Call_Strike[pos_3]-chain.Call_Strike[pos_2]) >= 2*(chain.Call_Strike[pos_2]-chain.Call_Strike[pos_1]) and (chain.Call_Strike[pos_3]-chain.Call_Strike[pos_2]) <= 9*(chain.Call_Strike[pos_2]-chain.Call_Strike[pos_1])
                if pos_1 < pos_2 and pos_2 < pos_3 and pos_cons:
                    allocation = np.zeros((chain.Call_total,2))
                    allocation[pos_1,0] = call_1_quantity
                    allocation[pos_2,0] = -1*call_2_quantity
                    allocation[pos_3,0] = call_3_quantity
                    strat = Strategy(allocation,chain,Strategy_name)
                    details = strat.summary()
                    if details["Strategy_left_leg"]>0 :
                        bear_call_fly_strat.append(strat)
                        bear_call_fly.append(details)
                                            
                        bear_pos = np.vstack((bear_pos,np.array([[pos_1,pos_2,pos_3]])))
                        bear_strike = np.vstack((bear_strike, np.array([[chain.Call_Strike[pos_1], chain.Call_Strike[pos_2], chain.Call_Strike[pos_3]]])))
                
            
                
            if len(bear_call_fly)>0:
                bear_call_fly_df = pd.DataFrame(bear_call_fly)
                bear_call_fly_df = bear_call_fly_df.sort_values(by=["Prob of Profit"], ascending=False)
    
                # Master_List_Strategies.append(bear_call_fly_strat)  
                print("\t \t Added ", len(bear_call_fly), " Strategies")
        
        
        """
        #######################################################################################
                                            Double Broken Butterfly                 
        #######################################################################################
        """ 
        
        
        double_fly_df =  pd.DataFrame()     
        if "General Double Broken Wing Butterfly" in Strategies:
            Strategy_name = "Double Broken Wing Butterfly"
            print("\t Processing ", Strategy_name, " Strategy")
            double_fly_details = list()
            double_fly_strats = list()
            
            for i in range(len(bear_call_fly_strat)):
                for j in range(len(bull_call_fly_strat)):
                    call_strat = bear_call_fly_strat[i]
                    put_strat = bull_call_fly_strat[j]
                    
                    bear_strikes = bear_strike[i,:]
                    bull_strikes = bull_strike[j,:]
                    
                    not_equal = bear_strikes[0] != bull_strikes[0] and bear_strikes[1] != bull_strikes[1] and bear_strikes[2] != bull_strikes[2]
                    
                    reflection = bear_strikes[2]+bull_strikes[0] <= 2*math.ceil(chain.Stock_Last) and bear_strikes[2]+bull_strikes[0] >= 2*math.floor(chain.Stock_Last)
                    
                    if not_equal and reflection :
                    
                        double_strat = combine_strat(call_strat, put_strat,chain)
                        details = double_strat.summary()  
                        if details["Total_Strikes"] == 7:
                            double_fly_details.append(details)
                            double_fly_strats.append(double_strat)
                
            if len(double_fly_details)>0:
                double_fly_df = pd.DataFrame(double_fly_details)
                double_fly_df = double_fly_df.sort_values(by=["Prob of Profit"], ascending=False)
                print("\t \t Added ", len(double_fly_details), " Strategies")
                
        
        """
        #######################################################################################
                                            Butterfly                 
        #######################################################################################
        """ 
    
        call_fly_df = pd.DataFrame()
        if "Butterfly" in Strategies:
            Strategy_name = "Butterfly"
            print("\t Processing ", Strategy_name, " Strategy")
            call_fly_strat = list()
            call_fly = list()
    
            call_1_pos = list(np.arange(chain.Call_total))
            call_2_pos = list(np.arange(chain.Call_total))
            call_3_pos = list(np.arange(chain.Call_total))
            call_1_quantity = 10#list(np.arange(1,max_quantity_per_leg+1))
            call_2_quantity = 20#list(np.arange(1,max_quantity_per_leg+1))
            call_3_quantity = 10#list(np.arange(1,max_quantity_per_leg+1))
            
            
            
            
            bear_pos = np.zeros((0,3))
            bear_strike = np.zeros((0,3))
            
            iterables = [call_1_pos,call_2_pos,call_3_pos]
            for t in itertools.product(*iterables):
                pos_1, pos_2, pos_3 = t
                pos_cons = (chain.Call_Strike[pos_3]-chain.Call_Strike[pos_2]) == (chain.Call_Strike[pos_2]-chain.Call_Strike[pos_1]) 
                if pos_1 < pos_2 and pos_2 < pos_3 and pos_cons:
                    allocation = np.zeros((chain.Call_total,2))
                    allocation[pos_1,0] = call_1_quantity
                    allocation[pos_2,0] = -1*call_2_quantity
                    allocation[pos_3,0] = call_3_quantity
                    strat = Strategy(allocation,chain,Strategy_name)
                    details = strat.summary()
                    # if details["Strategy_left_leg"]>0 :
                    call_fly_strat.append(strat)
                    call_fly.append(details)
                                        
                    bear_pos = np.vstack((bear_pos,np.array([[pos_1,pos_2,pos_3]])))
                    bear_strike = np.vstack((bear_strike, np.array([[chain.Call_Strike[pos_1], chain.Call_Strike[pos_2], chain.Call_Strike[pos_3]]])))
            
            
                
            if len(call_fly)>0:
                call_fly_df = pd.DataFrame(call_fly)
                call_fly_df = call_fly_df.sort_values(by=["Prob of Profit"], ascending=False)
    
                # Master_List_Strategies.append(bear_call_fly_strat)  
                print("\t \t Added ", len(call_fly), " Strategies")
        
        
        """
        #######################################################################################
                                            Iron Condor                 
        #######################################################################################
        """ 
        
        iron_con_df = pd.DataFrame()
        if "Iron Condor" in Strategies:
            Strategy_name = "Iron Condor"
            print("\t Processing ", Strategy_name, " Strategy")
            iron_con_strat = list()
            iron_con = list()
    
            call_1_pos = list(np.arange(chain.Call_total))
            call_2_pos = list(np.arange(chain.Call_total))
            put_1_pos = list(np.arange(chain.Put_total))
            put_2_pos = list(np.arange(chain.Put_total))  
            
            call_1_quantity = 10#list(np.arange(1,max_quantity_per_leg+1))
            call_2_quantity = 10#list(np.arange(1,max_quantity_per_leg+1))
            put_1_quantity = 10#list(np.arange(1,max_quantity_per_leg+1))
            put_2_quantity = 10#list(np.arange(1,max_quantity_per_leg+1))
            
            
            
            
            # bear_pos = np.zeros((0,3))
            # bear_strike = np.zeros((0,3))
            
            iterables = [call_1_pos,call_2_pos,put_1_pos, put_2_pos]
            for t in itertools.product(*iterables):
                c_pos_1, c_pos_2, p_pos_1, p_pos_2 = t
                pos_cons = (chain.Call_Strike[c_pos_2]-chain.Call_Strike[c_pos_1]) == (chain.Put_Strike[p_pos_2]-chain.Put_Strike[p_pos_1]) 
                if c_pos_1 < c_pos_2 and p_pos_1 < p_pos_2 and p_pos_2<c_pos_1 and pos_cons:
                    allocation = np.zeros((chain.Call_total,2))
                    allocation[c_pos_1,0] = -1*call_1_quantity
                    allocation[c_pos_2,0] = call_2_quantity
                    allocation[p_pos_1,1] = put_1_quantity
                    allocation[p_pos_2,1] = -1*put_2_quantity
                    strat = Strategy(allocation,chain,Strategy_name)
                    details = strat.summary()
                    # if details["Strategy_left_leg"]>0 :
                    iron_con_strat.append(strat)
                    iron_con.append(details)
                                        
                    # bear_pos = np.vstack((bear_pos,np.array([[pos_1,pos_2,pos_3]])))
                    # bear_strike = np.vstack((bear_strike, np.array([[chain.Call_Strike[pos_1], chain.Call_Strike[pos_2], chain.Call_Strike[pos_3]]])))
            
            
                
            if len(iron_con)>0:
                iron_con_df = pd.DataFrame(iron_con)
                iron_con_df = iron_con_df.sort_values(by=["Prob of Profit"], ascending=False)
    
                # Master_List_Strategies.append(bear_call_fly_strat)  
                print("\t \t Added ", len(iron_con), " Strategies")
    
        """
        Append all strategies of Underlying
        """
        # All_Strategies.append(Master_List_Strategies)
        if len(bull_call_fly_df)>0:
            Bull_Fly_Summary.append(bull_call_fly_df)
        else:
            Bull_Fly_Summary.append(pd.DataFrame())
        if len(bear_call_fly_df)>0:
            Bear_Fly_Summary.append(bear_call_fly_df)
        else:
            Bear_Fly_Summary.append(pd.DataFrame())
        
        if len(call_fly_df)>0:
            Fly_Summary.append(call_fly_df)
        else:
            Fly_Summary.append(pd.DataFrame())
        
        if len(iron_con_df)>0:
            Iron_Con_Summary.append(iron_con_df)
        else:
            Iron_Con_Summary.append(pd.DataFrame())
        
        if len(double_fly_df)>0:
            All_Strategies_Summary.append(double_fly_df)
        else:
            All_Strategies_Summary.append(pd.DataFrame())
        
    
            
    
    
    toc = datetime.now()
    
    print("\n Time Elapsed :", toc-tic)
        
       
    
    
    if save_results == True:
        for i in range(len(Assets)):
            # df_main = All_Strategies_Summary[i]
    
            df_bull = Bull_Fly_Summary[i]
            df_bear = Bear_Fly_Summary[i]
            df_fly = Fly_Summary[i]
            df_iron_con = Iron_Con_Summary[i]
            res_pred = predictions[i]
            res_pred_vol = predictions_vol[i]
            # if len(df_main.index)>=0:
            min_strat = min(len(df_bull),len(df_bear))
            print(min_strat)
            if min_strat >=10:
                outname = Assets[i]+".xlsx"
                fullname = os.path.join(path, outname)   
                with pd.ExcelWriter(fullname) as writer:
                    res_pred.to_excel(writer,sheet_name='Forecast', index=False)
                    res_pred_vol.to_excel(writer,sheet_name='Volatility', index=False)
                    df_iron_con.to_excel(writer,sheet_name= 'Iron Condor', index=False)
                    df_bull.to_excel(writer,sheet_name='Bull Broken', index=False)
                    df_bear.to_excel(writer,sheet_name='Bear Broken', index=False)
                    df_fly.to_excel(writer,sheet_name= 'Butterfly ', index=False)
                # df_main.to_excel(writer,sheet_name='Double Broken', index=False)
    
    
    
    
    # chain = All_Option_Chains[0]
    # allocation = np.zeros((chain.Call_total,2))
    # allocation[1,1]= 10
    # allocation[25,1] = -20
    # allocation[32,1] = 10
    # #allocation[3,0] = -1
    # #allocation[4,0] = 1
    # opt_strategy = Strategy(allocation,chain,"New")
    # cost = opt_strategy.initial_cost()
    # # pnl = opt_strategy.final_pnl(100)
    # # payoff = opt_strategy.payoff(100)
    # # cos = -1*(pnl-payoff)
    
    # # prob = opt_strategy.prob_profit()
    
    # # #total_pnl  = opt_strategy.pnl_space()
    # # print("PnL at S_T :", pnl)
    # # print(cost)
    # # print(payoff)
    # # print(cos)
    # # print("Expected PnL :", opt_strategy.expected_pnl() )
    # opt_strategy.plot_pnl()
    
    #f= 1<2 and 3<4




