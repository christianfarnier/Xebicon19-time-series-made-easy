# -*- coding: utf-8 -*-
# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.3.0
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from time import time
# %matplotlib inline
import matplotlib.pyplot as plt
import matplotlib
pd.options.display.max_columns = None
pd.options.display.max_rows = None
matplotlib.rcParams.update({'font.size': 22})
from pytz import timezone as tz
import gluonts

import sys
sys.path.append("..")
import src.constants.files as files
import src.constants.columns as c

# +
data_path = "./data/"
data_freq = "H"
max_epochs = 30
patience = 10
learning_rate = 0.0001

test_date = datetime(2019, 1, 1)
nb_hours_pred = 2*7*24
# -

df = (pd.read_csv(
        files.ENERGY_CONSUMPTION, sep=";", parse_dates=[c.EnergyConso.TIMESTAMP],
        usecols=[c.EnergyConso.REGION, c.EnergyConso.TIMESTAMP, c.EnergyConso.CONSUMPTION])
        .sort_values(by=[c.EnergyConso.REGION, c.EnergyConso.TIMESTAMP])
    )

date = df[c.EnergyConso.TIMESTAMP].iloc[0]

date_utc = date.astimezone(tz("UTC"))

datetime.fromtimestamp(date_utc.timestamp())

date

pd.isnull(df["Consommation (MW)"]).value_counts()

df.rename(columns={"Date - Heure": "Date"}, inplace=True)
df.fillna(df.dropna()["Consommation (MW)"].mean(), inplace=True)
df["date_heure"] = df["Date"].apply(lambda x: x + timedelta(minutes=x.minute))
df["date_heure"] = df["date_heure"].apply(lambda x: x.astimezone(tz("UTC")))
df["date_heure"] = df["date_heure"].apply(lambda x: x.fromtimestamp(x.timestamp()))
df.head(3)

df_hour = df.groupby(["Région", "date_heure"], as_index=False).agg({"Consommation (MW)": np.sum})
df_hour.head(3)

df_hour["Région"].value_counts()

print(df_hour["date_heure"].min(), df_hour["date_heure"].max())

full_meteo = pd.read_csv(data_path + "full_meteo.csv", parse_dates=["DATE"]).rename(
columns={"MAX_TEMP": "max_temp_paris"})[["DATE", "max_temp_paris"]]
last_meteo_paris = pd.read_csv(data_path + "meteo_paris_2019_juin_sept.csv",
                               sep=";", parse_dates=["DATE"]).rename(columns={"MAX_TEMP": "max_temp_paris"})
full_meteo = pd.concat([full_meteo, last_meteo_paris], axis=0)
full_meteo["DATE"] = full_meteo["DATE"].apply(lambda x: x.date())
full_meteo.head(1)

# +
df_temp = df_hour.copy()
df_temp["DATE"] = df_temp["date_heure"].apply(lambda x: x.date())

df_temp = pd.merge(df_temp, full_meteo[["DATE", "max_temp_paris"]], on="DATE", how="left").drop("DATE", axis=1)
df_temp = df_temp[df_temp["date_heure"] >= start_train_date]
df_temp.head(1)

# +
matplotlib.rcParams.update({'font.size': 22})
year = 2018
month = 12

plt.figure(1, figsize=(25, 12))
for region in pd.unique(df_temp["Région"]):
    df_region = df_temp[(df_temp["Région"]==region)
                        &(df_temp["date_heure"].apply(lambda x: x.year)==year)
                       &(df_temp["date_heure"].apply(lambda x: x.month==month))]
    plt.plot(df_region["date_heure"], df_region["Consommation (MW)"], label=region)
    plt.ylabel("Consommation (MW)")
    plt.legend()

plt.show()

# +
df_dict = {}

for region in pd.unique(df_temp["Région"]):
    df_dict[region] = df_temp[df_temp["Région"]==region].copy().reset_index(drop=True)
    df_dict[region].index = df_dict[region]["date_heure"]
    df_dict[region] = df_dict[region].reindex(
        pd.date_range(start=df_temp["date_heure"].min(), end=df_temp["date_heure"].max(), freq=data_freq)).drop(
        ["date_heure", "Région"], axis=1)
    df_dict[region]["max_temp_paris"] = df_dict[region]["max_temp_paris"].fillna(method="ffill")
# -

# # Fonctions pour entraînement DeepAR

# +
from gluonts.model.deepar import DeepAREstimator
from gluonts.trainer import Trainer
from gluonts.dataset.common import ListDataset
from gluonts.evaluation.backtest import make_evaluation_predictions

def train_predictor(df_dict, end_train_date, regions_list, target_col, feat_dynamic_cols=None):
    estimator = DeepAREstimator(freq=data_freq, 
                                prediction_length=nb_hours_pred,
                                trainer=Trainer(epochs=max_epochs, learning_rate = learning_rate,
                                                learning_rate_decay_factor=0.01, patience=patience),
                                use_feat_dynamic_real=feat_dynamic_cols is not None)
    if feat_dynamic_cols is not None:
        
        training_data = ListDataset(
            [{"item_id": region,
                "start": df_dict[region].index[0],
              "target": df_dict[region][target_col][:end_train_date],
             "feat_dynamic_real": [df_dict[region][feat_dynamic_col][:end_train_date]
                                   for feat_dynamic_col in feat_dynamic_cols] 
             }
            for region in regions_list],
            freq = data_freq
        )
    else:
        training_data = ListDataset(
            [{"item_id": region,
                "start": df_dict[region].index[0],
              "target": df_dict[region][target_col][:end_train_date]
             }
            for region in regions_list],
            freq = data_freq
        )

    predictor = estimator.train(training_data=training_data)
    
    return predictor


def make_predictions(predictor, df_dict, test_date, regions_list, target_col, feat_dynamic_cols=None):
    if feat_dynamic_cols is not None:
        test_data = ListDataset(
            [{"item_id": region,
                "start": df_dict[region].index[0],
              "target": df_dict[region][target_col][:test_date + timedelta(hours=nb_hours_pred)],
             "feat_dynamic_real": [df_dict[region][feat_dynamic_col][:test_date + timedelta(hours=nb_hours_pred)]
                                   for feat_dynamic_col in feat_dynamic_cols]
             }
            for region in regions_list],
            freq = data_freq
            )
    else:
         test_data = ListDataset(
            [{"item_id": region,
                "start": df_dict[region].index[0],
              "target": df_dict[region][target_col][:test_date + timedelta(hours=nb_hours_pred)],
             }
            for region in regions_list],
            freq = data_freq
            )

    forecast_it, ts_it = make_evaluation_predictions(test_data, predictor=predictor, num_eval_samples=100)
    
    return list(forecast_it), list(ts_it)


def plot_forecasts(df_dict, test_date, tss, forecasts, past_length, num_plots, figname):
    label_fontsize = 16
    for target, forecast in zip(tss, forecasts):
        ax = target[-past_length:].plot(figsize=(20, 8), linewidth=2)
        forecast.plot(color='g')
        plt.grid(which='both')
        plt.legend(["observations", "median prediction", "90% confidence interval", "50% confidence interval"])
        
        results_mean = forecast.mean
        ground_truth = df_dict[forecast.item_id]["Consommation (MW)"][
            test_date + timedelta(hours=1):test_date + timedelta(hours=nb_hours_pred)].values
        MAPE = np.mean(np.apply_along_axis(abs, 0, (ground_truth - results_mean) / ground_truth))
        plt.title(forecast.item_id + " MAPE:{}%".format(str(round(100*MAPE, 1))))
        plt.ylabel("Consumption (MW)")
        plt.xlabel("")
        ax.set_xlim([test_date - timedelta(days=nb_hours_pred/24), test_date + timedelta(days=nb_hours_pred/24)])
        ax.set_ylim([12000, 28000])
        xticks = [test_date + timedelta(days=x) for x in [-11, -7, -3, 0, 4, 8, 12]]
        ax.set_xticks(xticks, minor=True)
        ax.set_xticklabels([datetime.strftime(date, "%Y-%m-%d") for date in xticks if date != test_date],
                           minor=True, fontsize=label_fontsize)
        ax.set_xticklabels(["", datetime.strftime(test_date, "%Y-%m-%d"), ""], minor=False,
                           fontsize=label_fontsize)
        yticks = np.arange(14000, 28000, step=2000)
        ax.set_yticks(yticks)
        ax.set_yticklabels([str(x) for x in yticks], fontsize=label_fontsize)
        plt.savefig("./figures/{}.png".format(figname))
        plt.show()


# -

# # Test Île de France

# +
idf_list = ["Ile-de-France"]

idf_predictor = train_predictor(df_dict, end_train_date, idf_list,
                                target_col="Consommation (MW)", feat_dynamic_cols=None)
# -

matplotlib.rcParams.update({'font.size': 22})
forecasts, tss = make_predictions(idf_predictor, df_dict, test_date, idf_list, target_col="Consommation (MW)")
plot_forecasts(df_dict, test_date, tss, forecasts, past_length=2*nb_hours_pred, num_plots=1, figname="Paris seul")

# # Test sur toutes les régions

# +
all_regions = pd.unique(df["Région"])

all_reg_predictor = train_predictor(df_dict, end_train_date, all_regions,
                                    target_col="Consommation (MW)", feat_dynamic_cols=None)
# -

matplotlib.rcParams.update({'font.size': 22})
forecasts, tss = make_predictions(all_reg_predictor, df_dict, test_date, ["Ile-de-France"], target_col="Consommation (MW)")
plot_forecasts(df_dict, test_date, tss, forecasts, past_length=2*nb_hours_pred, num_plots=1, figname="Paris et autres régions")

# # Test Île de France avec température de Paris maximale du jour

# +
idf_list = ["Ile-de-France"]

temp_pred = train_predictor(df_dict, end_train_date, idf_list,
                                    target_col="Consommation (MW)", feat_dynamic_cols=["max_temp_paris"])
# -

matplotlib.rcParams.update({'font.size': 22})
forecasts, tss = make_predictions(temp_pred, df_dict, test_date, idf_list, target_col="Consommation (MW)",
                                 feat_dynamic_cols=["max_temp_paris"])
plot_forecasts(df_dict, test_date, tss, forecasts, past_length=2*nb_hours_pred, num_plots=1, figname="Paris et température")


