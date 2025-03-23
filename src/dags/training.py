import json
import logging
import os

import boto3
import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd
import yaml
from dotenv import load_dotenv
from imblearn.over_sampling import SMOTE
from kafka import KafkaConsumer
from mlflow.models import infer_signature
from numpy.array_api import astype
from sklearn.compose import ColumnTransformer
from sklearn.metrics import make_scorer, fbeta_score, precision_recall_curve, average_precision_score, precision_score, \
    recall_score, f1_score, confusion_matrix
from sklearn.model_selection import train_test_split, RandomizedSearchCV, StratifiedKFold
from sklearn.preprocessing import OrdinalEncoder
from xgboost import XGBClassifier
from imblearn.pipeline import Pipeline as ImbPipeline
import joblib

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(module)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler('./fraud_detection_model.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class FraudDetectionTraining:
    def __init__(self, config_path='/app/config.yaml'):
        os.environ['GIT_PYTHON_REFRESH'] = 'quiet'
        os.environ['GIT_PYTHON_GIT_EXECUTABLE'] = '/usr/bin/git'
        load_dotenv(dotenv_path='/app/.env')
        self.config = self._load_config(config_path)
        os.environ.update({
            'AWS_ACCESS_KEY_ID': os.getenv('AWS_ACCESS_KEY_ID'),
            'AWS_SECRET_ACCESS_KEY': os.getenv('AWS_SECRET_ACCESS_KEY'),
            'AWS_S3_ENDPOINT_URL': self.config['mlflow']['s3_endpoint_url']
        })
        self._validate_environment()
        mlflow.set_tracking_uri(self.config['mlflow']['tracking_uri'])
        mlflow.set_experiment(self.config['mlflow']['experiment_name'])
        
    def _load_config(self, config_path: str) -> dict:
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info('Configuration loaded correctly')
            return config
        except Exception as e:
            logger.error('Failed to load: %s', str(e))
            raise
            
    def _validate_environment(self):
        required_vars = ['KAFKA_BOOTSTRAP_SERVERS', 'KAFKA_PASSWORD', 'KAFKA_USERNAME']
        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            raise ValueError(f'Missing required environment variables {missing}')
       
        self._check_minio_connection()
        
    def _check_minio_connection(self):
        try:
            s3 = boto3.client(
                's3',
                endpoint_url=self.config['mlflow']['s3_endpoint_url'], 
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
            )
            buckets = s3.list_buckets()
            bucket_names = [b['Name'] for b in buckets.get('Buckets', [])]
            logger.info('Minio connection verified. Buckets: %s', bucket_names)
            mlflow_bucket = self.config['mlflow'].get('bucket', 'mlflow')
            if mlflow_bucket not in bucket_names:
                s3.create_bucket(Bucket=mlflow_bucket)
                logger.info('Created missing MLFlow bucket: %s', mlflow_bucket)
        except Exception as e:
            logger.error('Minio connection failed: %s', str(e))

    def read_from_kafka(self) -> pd.DataFrame:
        try:
            topic = self.config['kafka']['topic']
            logger.info('Connecting to kafka topic %s', topic)

            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=self.config['kafka']['bootstrap_servers'],
                security_protocol='SASL_SSL',
                sasl_mechanism='PLAIN',
                sasl_plain_username=self.config['kafka']['username'],
                sasl_plain_password=self.config['kafka']['password'],
                value_deserializer=lambda x: json.loads(x.decode('utf-8')),
                consumer_timeout_ms=self.config['kafka'].get('timeout', 10000)
            )

            messages = [msg.value for msg in consumer]
            consumer.close()

            df = pd.DataFrame(messages)
            if df.empty:
                raise ValueError('Empty Kafka topic')
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
                                             
            if 'is_fraud' not in df.columns:
                raise ValueError('Fraud label (is_fraud) is missing')    
            
            fraud_rate = df['is_fraud'].mean() * 100
            logger.info('Kafka topic read correctly with fraud rate: %.2f%%', fraud_rate)

            return df

        except Exception as e:
            logger.error('Error reading topic from kafka: %s', str(e), exc_info=True)
            raise

    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values(['user_id', 'timestamp']).copy()

        # ---- temporal features ----
        # hour of the txn
        df['transaction_hour'] = df['timestamp'].dt.hour
        # flags txns happening at night (22:00 - 5:00)
        df['is_night'] = ((df['transaction_hour'] >= 22) | (df['transaction_hour'] < 5)).astype(int)
        # flag txns happenig on weekends (saturdays=5 and sundays=6)
        df['is_weekend'] = (df['timestamp'].dt.dayofweek >= 5).astype(int)
        #txn day
        df['transaction_day'] = df['timestamp'].dt.day

        # -- behavioural features
        df['user_activity_24h'] = df.groupby('user_id', group_keys=False).apply(
            lambda g: g.rolling('24h', on='timestamp', closed='left')['amount'].count().fillna(0)
        )

        # -- monetary feature -- 
        df['amount_to_avg_ratio'] = df.groupby('user_id', group_keys=False).apply(
            lambda g: (g['amount'] / g['amount'].rolling(7, min_periods=1).mean()).fillna(1.0)
        )

        # -- merchant feature --
        high_risk_merchant = self.config.get('high_risk_merchants', ['Quickcash', 'GlobalDigital', 'FastMoneyX'])
        df['merchant_risk'] = df['merchant'].isin(high_risk_merchant).astype(int)

        features_cols = [
            'amount', 'is_night', 'is_weekend', 'transaction_day', 'user_activity_24h',
            'amount_to_avg_ratio', 'merchant_risk', 'merchant'
        ]

        if 'is_fraud' not in df.columns:
            raise ValueError('Missing target column "is_fraud"')
        
        return df[features_cols + ['is_fraud']]

    def train_model(self):
        try:
            logger.info('Starting model training')
            
            # raw transactions from kafka as dataframe
            df = self.read_from_kafka()

            # start faeture engineering 
            data = self.create_features(df)

            # split the data into features (X) and target (Y)
            X = data.drop(columns=['is_fraud'])
            y = data['is_fraud']

            if y.sum() == 0:
                raise ValueError('No positive samples in training data')
            
            if y.sum() < 10:
                logger.warning('Low positive samples: %d. Consider data augmentation', y.sum())

            X_train, X_test, y_train, y_test = train_test_split(
                X, y,
                test_size=self.config['model'].get('test_size', 0.2),
                stratify=y,
                random_state=self.config['model'].get('seed', 42)
            )

            with mlflow.start_run():
                mlflow.log_metrics({
                    'train_samples': X_train.shape[0],
                    'positive_samples': int(y_train.sum()),
                    'class_ratio': float(y_train.mean()),
                    'test_samples': X_test.shape[0]
                })

                preprocessor = ColumnTransformer(
                    [
                        ('merchant_encoder', OrdinalEncoder(
                            handle_unknown='use_encoded_value', unknown_value=-1, dtype=np.float32
                        ), ['merchant'])
                    ], remainder='passthrough'
                )

                xgb = XGBClassifier(
                    eval_metric='aucpr',
                    random_state=self.config['model'].get('seed', 42),
                    reg_lambda=1.0,
                    n_estimators=self.config['model']['params']['n_estimators'],
                    n_jobs=-1,
                    tree_method=self.config['model'].get('tree_method', 'hist')
                )

                # -- pipeline construction --
                #preprocessing
                #class imbalance handling with SMOTE
                #prediction with xghboost classifier
                pipeline = ImbPipeline ([
                    ('preprocessor', preprocessor),
                    ('smote', SMOTE(random_state=self.config['model'].get('seed', 42))), ('classifier', xgb)
                ], memory='./cache')

                # Hyperparameter search space design
                param_dist = {
                    'classifier__max_depth': [3, 5, 7],  # Depth control for regularization
                    'classifier__learning_rate': [0.01, 0.05, 0.1],  # Conservative range
                    'classifier__subsample': [0.6, 0.8, 1.0],  # Stochastic gradient boosting
                    'classifier__colsample_bytree': [0.6, 0.8, 1.0],  # Feature randomization
                    'classifier__gamma': [0, 0.1, 0.3],  # Complexity control
                    'classifier__reg_alpha': [0, 0.1, 0.5]  # L1 regularization
                }

                # Optimizing for F-beta score (beta=2 emphasizes recall)
                searcher = RandomizedSearchCV(
                    pipeline,
                    param_dist,
                    n_iter=20,
                    scoring=make_scorer(fbeta_score, beta=2, zero_division=0),
                    cv=StratifiedKFold(n_splits=3, shuffle=True),
                    n_jobs=-1,
                    refit=True,
                    error_score='raise',
                    random_state=self.config['model'].get('seed', 42)
                )

                logger.info('Starting hyperparameter tuning...')
                searcher.fit(X_train, y_train)
                best_model = searcher.best_estimator_
                best_params = searcher.best_params_
                logger.info('Best hyperparameters: %s', best_params)

                # Threshold optimization using training data
                train_proba = best_model.predict_proba(X_train)[:, 1]
                precision_arr, recall_arr, thresholds_arr = precision_recall_curve(y_train, train_proba)
                f1_scores = [2 * (p * r) / (p + r) if (p + r) > 0 else 0 for p, r in
                             zip(precision_arr[:-1], recall_arr[:-1])]
                best_threshold = thresholds_arr[np.argmax(f1_scores)]
                logger.info('Optimal threshold determined: %.4f', best_threshold)

                # Model evaluation
                X_test_processed = best_model.named_steps['preprocessor'].transform(X_test)
                test_proba = best_model.named_steps['classifier'].predict_proba(X_test_processed)[:, 1]
                y_pred = (test_proba >= best_threshold).astype(int)

                # Comprehensive metrics suite
                metrics = {
                    'auc_pr': float(average_precision_score(y_test, test_proba)),
                    'precision': float(precision_score(y_test, y_pred, zero_division=0)),
                    'recall': float(recall_score(y_test, y_pred, zero_division=0)),
                    'f1': float(f1_score(y_test, y_pred, zero_division=0)),
                    'threshold': float(best_threshold)
                }

                mlflow.log_metrics(metrics)
                mlflow.log_params(best_params)

                # Confusion matrix visualization
                cm = confusion_matrix(y_test, y_pred)
                plt.figure(figsize=(6, 4))
                plt.imshow(cm, interpolation='nearest', cmap=plt.cm.Blues)
                plt.title('Confusion Matrix')
                plt.colorbar()
                tick_marks = np.arange(2)
                plt.xticks(tick_marks, ['Not Fraud', 'Fraud'])
                plt.yticks(tick_marks, ['Not Fraud', 'Fraud'])

                for i in range(2):
                    for j in range(2):
                        plt.text(j, i, format(cm[i, j], 'd'), ha='center', va='center', color='red')

                plt.tight_layout()
                cm_filename = 'confusion_matrix.png'
                plt.savefig(cm_filename)
                mlflow.log_artifact(cm_filename)
                plt.close()

                # Precision-Recall curve documentation
                plt.figure(figsize=(10, 6))
                plt.plot(recall_arr, precision_arr, marker='.', label='Precision-Recall Curve')
                plt.xlabel('Recall')
                plt.ylabel('Precision')
                plt.title('Precision-Recall Curve')
                plt.legend()
                pr_filename = 'precision_recall_curve.png'
                plt.savefig(pr_filename)
                mlflow.log_artifact(pr_filename)
                plt.close()

                # Model packaging and registry
                signature = infer_signature(X_train, y_pred)
                mlflow.sklearn.log_model(
                    sk_model=best_model,
                    artifact_path='model',
                    signature=signature,
                    registered_model_name='fraud_detection_model'
                )

                # Model serialization for deployment
                os.makedirs('/app/models', exist_ok=True)
                joblib.dump(best_model, '/app/models/fraud_detection_model.pkl')

                logger.info('Training successfully completed with metrics: %s', metrics)

                return best_model, metrics

        except Exception as e:
            logger.error('Training failed: %s', str(e), exc_info=True)
            raise