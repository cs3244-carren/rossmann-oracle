#!/usr/bin/python3.5
import sys
import pandas as pd
import numpy as np
import settings
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from keras.models import Sequential
from keras.layers import Dense

# feature params
ALL_FEATURES = ['Store', 'DayOfWeek', 'Date', 'Sales', 'Customers', 'Open', 'Promo', 'StateHoliday',
                'SchoolHoliday', 'StoreType', 'Assortment', 'CompetitionDistance',
                'CompetitionOpenSinceMonth', 'CompetitionOpenSinceYear', 'Promo2', 'Promo2SinceWeek',
                'Promo2SinceYear', 'PromoInterval', 'DateOfCompetitionOpen', 'IsInCompetition']
TRAIN_FEATURES = []
TEST_FEATURES = list(TRAIN_FEATURES)


def remove_closed_stores(df):
    """
    Returns a pd.DataFrame without closed stores.
    (closed means 'Open' == 0)
    :param df:
    :return: a DataFrame without closed stores.
    """
    return df[df['Open'] != 0]


def one_hot_encode(df, target, prefix, excludes=None):
    """
    Perform one-hot encoding for a target column in a given pd.DataFrame
    :param df:
    :param target: (str) name of the column to one-hot encode
    :param prefix: (str) prefix of the encoding variables
    :param excludes: (list) of encoded column names to drop (including prefix)
    :return:
    """
    dummy = pd.get_dummies(df[target], prefix=prefix)
    if excludes is not None:
        dummy.drop(excludes, axis=1, inplace=True)
    df.drop([target], axis=1, inplace=True)
    return df.join(dummy)


def generate_month_feature(df):
    df['Month'] = df['Date'].str[5:7]
    df['Month'] = df['Month'].astype(int)
    return df


def generate_year_feature(df):
    df['Year'] = df['Date'].str[0:5]
    df['Year'] = df['Year'].astype(int)
    return df


def get_month_numeric(month):
    dictionary = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6, 'Jul': 7,
                  'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}
    return dictionary.get(month, default=None)

def prepare_data(df, to_drop, has_y=False, store=None):
    """
    Performs the common train/test feature engineering procedures
    :param df:
    :param to_drop: (list) of column names to drop from both train and test sets
    :param has_y: (bool) does the df contain the y variable of interest?
    :return:
    """
    #df = generate_month_feature(df) # add Month feature
    #df = generate_year_feature(df) # add Year feature

    # drop features we don't need
    df = df.drop(to_drop, axis=1)

    # append features from store.csv
    if store is not None:
        store_to_drop = ['StoreType','Assortment','CompetitionDistance', 'CompetitionOpenSinceMonth',
                         'CompetitionOpenSinceYear','Promo2','Promo2SinceWeek', 'Promo2SinceYear','PromoInterval']
        #df['Promo2'] = pd.merge(df, store['Promo2'].astype(int), how='outer')

    # one-hot encode StateHoliday
    df['StateHoliday'] = df['StateHoliday'].astype(str)
    df = one_hot_encode(df, 'StateHoliday', 'StateHoliday', excludes=None)
    for var in ['StateHoliday_0', 'StateHoliday_a', 'StateHoliday_b', 'StateHoliday_c']:
        if var not in df.columns.values:
            df[var] = 0

    # norm customers using log_2
    df['Customers'] = df['Customers'].replace([0], [0.0001])  # prevent nans
    df['Customers'] = np.log2(df['Customers'])

    # one-hot encode dayofweek
    df = one_hot_encode(df, 'DayOfWeek', 'Day', excludes=None)
    for var in ['Day_1', 'Day_2', 'Day_3', 'Day_4', 'Day_5', 'Day_6', 'Day_7']:
        if var not in df.columns.values:
            df[var] = 0

    # append Id column
    df['Id'] = df.index

    # normalize sales using log_2 (only applicable for training data)
    if has_y:
        df['Sales'] = df['Sales'].replace([0], [0.0001])  # prevent nans
        df['Sales'] = np.log2(df['Sales'])

    return df


def extract_closed_store_ids(df):
    """
    Gets a list of IDs for stores that are closed in df
    :param df:
    :return: the IDs of stores that are closed in df
    """
    return df[df['Open'] == 0]['Id']


train = pd.read_csv(settings.CSV_TRAIN, low_memory=False)
test = pd.read_csv(settings.CSV_TEST, low_memory=False)
store = pd.read_csv(settings.CSV_STORE, low_memory=False)

train = prepare_data(train, to_drop=['Date'], has_y=True, store=store)
train = remove_closed_stores(train)

test = prepare_data(test, to_drop=['Date'], has_y=False, store=store)


def split_open_closed(test_df):
    closed_store_ids = extract_closed_store_ids(test_df)
    test_df = remove_closed_stores(test_df)
    test_df = test_df.drop(['Open'], axis=1)
    return closed_store_ids, test_df


def save_for_submission_csv(closed_store_ids, open_store_sales, outfile):
    open_store_sales = pd.DataFrame(
        {'Id': open_store_sales.index + 1, 'Sales': np.power(2, open_store_sales.values)})
    closed_store_sales = pd.DataFrame(
        {'Id': closed_store_ids + 1, 'Sales': 1})  # 0 sales need to be map to 1 for kaggle
    submission = pd.concat([open_store_sales, closed_store_sales])
    submission.to_csv(outfile, index=False)
    return


def train_many_models(train_df, test_df, outfile='output.csv', model_type='linear-regression', verbose=False):
    """
    Trains a random forest for each store and generates predictions for all testing input
    :param train_df: processed dataframe of training data
    :param test_df: processed dataframe of testing data (should not have Sales column)
    :param model_type: type of model to train
    :param outfile: name of the output file to write predictions to
    :return:
    """
    print_feature_list = True
    print('\nTraining many %s models' % model_type)
    # special case for closed stores where sales = 0 (or 1 for kaggle's purposes)
    closed_store_ids, test_df = split_open_closed(test_df)

    train_stores = dict(list(train_df.groupby('Store')))
    test_stores = dict(list(test_df.groupby('Store')))
    open_store_sales = pd.Series()
    train_scores = []
    for i in test_stores:
        current_store = train_stores[i]

        # define training and testing sets
        train_x = current_store.drop(['Id', 'Sales', 'Store', 'Open'], axis=1)

        if print_feature_list:
            print('Features: %s' % train_x.columns.values.tolist())
            print_feature_list = False

        train_y = current_store['Sales']

        test_x = test_stores[i].copy()
        open_store_ids = test_x['Id']
        test_x = test_x.drop(['Id', 'Store'], axis=1)

        model = None
        if model_type == 'linear-regression':
            model = LinearRegression()
        elif model_type == 'random-forest':
            model = RandomForestRegressor(n_estimators=100, max_depth=10, oob_score=True)
        else:
            model = LinearRegression()

        model.fit(train_x, train_y)
        test_y = model.predict(test_x)
        train_scores.append(model.score(train_x, train_y))

        # append predicted values of current store to submission
        open_store_sales = open_store_sales.append(pd.Series(test_y, index=open_store_ids))

        if verbose:
            print('Completed Store %d: train_score=%.5f' % (i, train_scores[-1]))

    # save to csv file
    save_for_submission_csv(closed_store_ids, open_store_sales, outfile)
    print('mean(train_score)=%.5f' % np.mean(train_scores))
    print('sd(train_score)=%.5f' % np.std(train_scores))
    print('done: wrote predictions to %s' % outfile)
    return


def train_single_model(train_df, test_df, model_type='linear-regression', outfile='out.csv'):
    print('\nTraining monolithic %s model' % model_type)
    # special case for closed stores where sales = 0 (or 1 for kaggle's purposes)
    closed_store_ids, test_df = split_open_closed(test_df)

    train_y = train_df['Sales']
    train_x = train_df.drop(['Id', 'Sales', 'Open', 'Store'], axis=1)

    open_store_ids = test_df['Id']
    test_x = test_df.drop(['Id', 'Store'], axis=1)

    print('Features: %s' % train_x.columns.values.tolist())

    model = None
    if model_type == 'linear-regression':
        model = LinearRegression()
    elif model_type == 'random-forest':
        model = RandomForestRegressor(n_estimators=100, max_depth=10, oob_score=True)
    else:
        model = LinearRegression()

    model.fit(train_x, train_y)

    test_y = model.predict(test_x)
    train_score = model.score(train_x, train_y)

    open_store_sales = pd.Series().append(pd.Series(test_y, index=open_store_ids))

    # save to csv file
    save_for_submission_csv(closed_store_ids, open_store_sales, outfile)
    print('train_score=%.5f' % train_score)
    print('done: wrote predictions to %s' % outfile)
    return


def train_single_keras_model(train_df, test_df, outfile='out.csv'):
    print('\nTraining keras model')
    # special case for closed stores where sales = 0 (or 1 for kaggle's purposes)
    closed_store_ids, test_df = split_open_closed(test_df)

    train_y = train_df['Sales']
    train_x = train_df.drop(['Id', 'Sales', 'Open', 'Store'], axis=1)

    open_store_ids = test_df['Id']
    test_x = test_df.drop(['Id', 'Store'], axis=1)

    print('Features: %s' % train_x.columns.values.tolist())

    # cast to numpy arrays for keras
    train_x = np.array(train_x)
    train_y = np.array(train_y)
    test_x = np.array(test_x)

    # create model
    model = Sequential()
    model.add(Dense(np.shape(train_x)[1], input_dim=np.shape(train_x)[1], kernel_initializer='normal', activation='relu'))
    model.add(Dense(512, kernel_initializer='normal'))
    model.add(Dense(64, kernel_initializer='normal'))
    model.add(Dense(1))
    model.compile(loss='mean_squared_error', optimizer='adam')

    model.fit(train_x, train_y, epochs=25, batch_size=64, verbose=0, shuffle=True)
    test_y = model.predict(test_x)

    open_store_sales = pd.Series().append(pd.Series(test_y.ravel(), index=open_store_ids))
    save_for_submission_csv(closed_store_ids, open_store_sales, outfile)
    print('done: wrote predictions to %s' % outfile)
    return


def train_many_keras_models(train_df, test_df, outfile='output.csv', verbose=False):
    """
    Trains a random forest for each store and generates predictions for all testing input
    :param train_df: processed dataframe of training data
    :param test_df: processed dataframe of testing data (should not have Sales column)
    :param model_type: type of model to train
    :param outfile: name of the output file to write predictions to
    :return:
    """
    print_feature_list = True
    print('\nTraining many keras models')
    # special case for closed stores where sales = 0 (or 1 for kaggle's purposes)
    closed_store_ids, test_df = split_open_closed(test_df)

    train_stores = dict(list(train_df.groupby('Store')))
    test_stores = dict(list(test_df.groupby('Store')))
    open_store_sales = pd.Series()
    for i in test_stores:
        current_store = train_stores[i]

        # define training and testing sets
        train_x = current_store.drop(['Id', 'Sales', 'Store', 'Open'], axis=1)

        if print_feature_list:
            print('Features: %s' % train_x.columns.values.tolist())
            print_feature_list = False

        train_y = current_store['Sales']

        test_x = test_stores[i].copy()
        open_store_ids = test_x['Id']
        test_x = test_x.drop(['Id', 'Store'], axis=1)

        # cast to numpy arrays for keras
        train_x = np.array(train_x)
        train_y = np.array(train_y)
        test_x = np.array(test_x)

        # create model
        model = Sequential()
        model.add(Dense(np.shape(train_x)[1], input_dim=np.shape(train_x)[1], kernel_initializer='normal', activation='relu'))
        model.add(Dense(512, kernel_initializer='normal'))
        model.add(Dense(64, kernel_initializer='normal'))
        model.add(Dense(1))
        model.compile(loss='mean_squared_error', optimizer='adam')

        model.fit(train_x, train_y, epochs=50, batch_size=32, verbose=0, shuffle=True)
        test_y = model.predict(test_x)

        # append predicted values of current store to submission
        open_store_sales = open_store_sales.append(pd.Series(test_y.ravel(), index=open_store_ids))

        if verbose:
            print('Completed Store %d' % i)

    # save to csv file
    save_for_submission_csv(closed_store_ids, open_store_sales, outfile)
    print('done: wrote predictions to %s' % outfile)
    return


train_many_models(train, test, outfile='rossmann-lr-per-store.csv', model_type='linear-regression', verbose=False)
train_many_models(train, test, outfile='rossmann-rf-per-store.csv', model_type='random-forest', verbose=False)
train_single_model(train, test, outfile='rossmann-lr-all-stores.csv', model_type='linear-regression')
train_single_model(train, test, outfile='rossmann-rf-all-stores.csv', model_type='random-forest')
train_single_keras_model(train, test, outfile='rossmann-keras-all.csv')
train_many_keras_models(train, test, outfile='rossmann-keras-all.csv', verbose=True)
