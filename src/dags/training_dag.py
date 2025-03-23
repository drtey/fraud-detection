from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from airflow.exceptions import AirflowException

import logging

logger = logging.getLogger(__name__)

default_args = {
    'owner': 'drtey',
    'depends_on_past': False,
    'start_date': datetime(2025, 3, 20),
    # 'execution_timeout': timedelta(minutes=120),
    'max_active_runs': 1,
}

def _train_model():
    """Airflow wrapper for training task"""
    from training import FraudDetectionTraining
    try:
        logger.info('Starting fraud dection training')
        trainer = FraudDetectionTraining()
    except Exception as e:
        logger.error('Training failed %s', str(e), exc_info=True)
        raise AirflowException(f'Model training failed: {str(e)}')
    
    return {'status': 'success'}

with DAG(
    'DAG_fraud_training',
    default_args=default_args,
    description='Fraud detection model training pipeline',
    schedule_interval='0 3 * * *',
    catchup=False,
    tags=['fraud', 'ML']
) as dag:
    validate_environment = BashOperator(
        task_id='validate_environment',
        bash_command=''' 
            echo "Validating environment..."
            test -f /app/config.yaml &&
            test -f /app/.env &&
            echo "Environment is valid"
        '''
    )

    training_task = PythonOperator(
        task_id='execute_training',
        python_callable=_train_model
    )

    cleanup_task = BashOperator(
        task_id='cleanup_resources',
        bash_command='rm -f /app/tmp/*.pkl',
        trigger_rule='all_done'
    )

    validate_environment >> training_task >> cleanup_task


    # docs 
    dag.doc_md = """
    ## Fraud detection training pipeline

    Daily training of fraud detection model using:
    - Transaction data from Kafka
    - XGBoost classifier with precision optimisation
    - MLFlow for experiment tracking
    """