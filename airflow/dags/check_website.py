import os
import shutil
import re
import json
import logging
from datetime import timedelta
from pathlib import Path
import itertools
from typing import Dict, List, Tuple

import tenacity
from tenacity import retry

import airflow
from airflow import DAG
from airflow.sensors.http_sensor import HttpSensor
from airflow.hooks.http_hook import HttpHook
from airflow.hooks.base_hook import BaseHook
from airflow.models import Variable
from airflow.operators.python_operator import PythonOperator, ShortCircuitOperator

import requests

from operations import check_website_operations


Logger = logging.getLogger(__name__)

default_args = {
    "owner": "airflow",
    "start_date": airflow.utils.dates.days_ago(2),
    "provide_context": True,
    "depends_on_past": False,
}

dag = DAG(
    dag_id="check_website",
    default_args=default_args,
    schedule_interval=None,
)

def get_uri_list_file_path(
    xc_sps_packages_dir: Path, proc_sps_packages_dir: Path, execution_date: str
) -> str:
    """Garante que a uri_list usada será a do diretório de PROC. Quando for a primeira
    execução da DAG, a lista será copiada para o diretório de PROC. Caso contrário, a 
    mesma será mantida.
    """
    _uri_list_filename = f"uri_list_{execution_date}.lst"
    _uri_list_file_path = proc_sps_packages_dir / _uri_list_filename
    if not _uri_list_file_path.is_file():
        _origin_uri_list_file_path = xc_sps_packages_dir / _uri_list_filename
        Logger.info(
            'Copying original uri_list "%s" to proc "%s"',
            _origin_uri_list_file_path,
            _uri_list_file_path,
        )
        shutil.copy(_origin_uri_list_file_path, _uri_list_file_path)
    if not _uri_list_file_path.is_file():
        raise FileNotFoundError(_uri_list_file_path)

    return str(_uri_list_file_path)


def check_website_uri_list(conf, **kwargs):
    """Executa ``check_website.check_website_uri_list`` com a 
    uri_list referente à DagRun. 
    """
    gerapadrao_id_items = Variable.get(
        "GERAPADRAO_ID_FOR_URI_LIST", default_var=[], deserialize_json=True)

    _website_url_list = Variable.get("WEBSITE_URL_LIST", default_var=[], deserialize_json=True)
    if not _website_url_list:
        raise ValueError(
            "Unable to check the Web site resources are available "
            "because no Website URL (`Variable[\"WEBSITE_URL_LIST\"]`) was informed")

    _xc_sps_packages_dir = Path(Variable.get("XC_SPS_PACKAGES_DIR"))
    _proc_sps_packages_dir = Path(Variable.get("PROC_SPS_PACKAGES_DIR")) / kwargs["run_id"]
    if not _proc_sps_packages_dir.is_dir():
        _proc_sps_packages_dir.mkdir()

    for gerapadrao_id in gerapadrao_id_items:
        # obtém o caminho do arquivo que contém a lista de URI
        _uri_list_file_path = get_uri_list_file_path(
            _xc_sps_packages_dir,
            _proc_sps_packages_dir,
            gerapadrao_id,
        )
        # obtém o conteúdo do arquivo que contém a lista de URI
        # Exemplo do conteúdo de `_uri_list_file_path`:
        # /scielo.php?script=sci_serial&pid=0001-3765
        # /scielo.php?script=sci_issues&pid=0001-3765
        # /scielo.php?script=sci_issuetoc&pid=0001-376520200005
        # /scielo.php?script=sci_arttext&pid=S0001-37652020000501101
        uri_list_items = check_website_operations.read_file(_uri_list_file_path)

        # concatena cada item de `_website_url_list` com
        # cada item de `uri_list_items`
        website_uri_list = check_website_operations.concat_website_url_and_uri_list_items(
            _website_url_list, uri_list_items)

        # verifica a lista de URI
        check_website_operations.check_website_uri_list(website_uri_list)

    # atribui um str vazia para sinalizar que o valor foi usado
    Variable.set("GERAPADRAO_ID_FOR_URI_LIST", [], serialize_json=True)


check_website_uri_list_task = PythonOperator(
    task_id="check_website_uri_list_id",
    provide_context=True,
    python_callable=check_website_uri_list,
    dag=dag,
)


check_website_uri_list_task
