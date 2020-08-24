import logging
import requests
import time
from urllib3.exceptions import MaxRetryError, NewConnectionError

from bs4 import BeautifulSoup

from operations.docs_utils import (
    is_pid_v2,
    get_document_manifest,
    get_document_data_to_generate_uri,
    get_document_assets_data,
    get_document_renditions_data,
)

Logger = logging.getLogger(__name__)


def check_uri_items_expected_in_webpage(uri_items_expected_in_webpage,
                                 assets_data, other_versions_uri_data):
    """
    Verifica os recursos de um documento, comparando os recursos registrados
    no Kernel com os recursos indicados na página do documento no site público

    Args:
        uri_items_expected_in_webpage (list): Lista de recursos que foram encontrados
            dentro da página do documento
        assets_data (list of dict, retorno de `get_document_assets_data`):
            Dados de uri dos ativos digitais.
        other_versions_uri_data (list of dict,
            mesmo formato `retornado de get_document_webpage_uri_list`):
            Dados da uri de outras páginas do documento,
            ou seja, outro idioma e outro formato

    Returns:
        list of dict: resultado da verficação de cada recurso avaliado,
            mais dados do recurso
    """
    results = []
    for asset_data in assets_data:
        # {"prefix": prefix, "uri_alternatives": [],}
        uri_result = {}
        uri_result["type"] = "asset"
        uri_result["id"] = asset_data["prefix"]
        uri_result["found"] = False
        for uri in asset_data["uri_alternatives"]:
            if uri in uri_items_expected_in_webpage:
                # se uma das alternativas foi encontrada no html, found é True
                # e é desnecessário continuar procurando
                uri_result["uri"] = uri
                uri_result["found"] = True
                break
        if uri_result["found"] is False:
            uri_result["uri"] = asset_data["uri_alternatives"]
        results.append(uri_result)

    for other_version_uri_data in other_versions_uri_data:
        # {"doc_id": "", "lang": "", "format": "", "uri": ""},
        uri_result = {}
        uri_result["type"] = other_version_uri_data["format"]
        uri_result["id"] = other_version_uri_data["lang"]
        uri_result["found"] = False
        uri_list = (
            get_document_webpage_uri(
                other_version_uri_data, ("format", "lang")),
            get_document_webpage_uri(
                other_version_uri_data, ("lang", "format")),
            get_document_webpage_uri(
                other_version_uri_data, ("format",))
        )
        for uri in uri_list:
            if uri in uri_items_expected_in_webpage:
                # se uma das alternativas foi encontrada no html, found é True
                # e é desnecessário continuar procurando
                uri_result["uri"] = uri
                uri_result["found"] = True
                break
        if uri_result["found"] is False:
            uri_result["uri"] = uri_list
        results.append(uri_result)
    return results


def get_classic_document_webpage_uri(data):
    """
    Recebe data
    retorna uri no padrao
    /scielo.php?script=sci_arttext&pid=S0001-37652020000501101&tlng=lang
    /scielo.php?script=sci_pdf&pid=S0001-37652020000501101&tlng=lang
    """
    if data.get("format") == "pdf":
        script = "sci_pdf"
    else:
        script = "sci_arttext"
    uri = "/scielo.php?script={}&pid={}".format(script, data['doc_id'])
    if data.get("lang"):
        uri += "&tlng={}".format(data.get("lang"))
    return uri


def get_document_webpage_uri(data, query_param_names=None):
    """
    Recebe data
    retorna uri no padrao /j/:acron/a/:id_doc?format=pdf&lang=es
    """
    uri = "/j/{}/a/{}".format(data['acron'], data['doc_id'])
    query_param_names = query_param_names or ("format", "lang")
    query_items = [
        "{}={}".format(name, data.get(name))
        for name in query_param_names
        if data.get(name)
    ]
    if len(query_items):
        uri += "?" + "&".join(query_items)
    return uri


def get_document_webpage_uri_list(doc_id, doc_data_list, doc_webpage_uri_function=None):
    """
    Acrescenta aos items (dicionários) da lista `doc_data_list`, as chaves:
        "doc_id", "uri"
    Retorna
        [
            {
                "doc_id": "",
                "lang": "",
                "format": "",
                "uri": "",
            },
            {
                "doc_id": "",
                "lang": "",
                "format": "",
                "uri": "",
            },
        ]
    """
    acron = None
    pid_v2 = None
    if len(doc_data_list):
        doc_data = doc_data_list[0]
        acron = doc_data.get("acron")
        pid_v2 = doc_data.get("pid_v2")
    doc_webpage_uri_function = doc_webpage_uri_function or get_classic_document_webpage_uri
    if doc_webpage_uri_function == get_document_webpage_uri and not acron:
        raise ValueError("get_document_webpage_uri_list requires `acron`")
    if doc_webpage_uri_function == get_classic_document_webpage_uri and not is_pid_v2(pid_v2):
        raise ValueError("get_document_webpage_uri_list requires `pid v2`")
    uri_items = []
    for doc_data in doc_data_list:
        data = {
            "doc_id": doc_id,
        }
        doc_data.update(data)
        doc_data["uri"] = doc_webpage_uri_function(doc_data)
        uri_items.append(doc_data)
    return uri_items


def get_webpage_content(uri):
    response = access_uri(uri, requests.get)
    if response:
        return response.text


def get_webpage_href_and_src(content):
    href_items = {}

    soup = BeautifulSoup(content)

    href_items["href"] = [
        link.get('href')
        for link in soup.find_all('a')
        if link.get('href')
    ]
    href_items["src"] = [
        link.get('src')
        for link in soup.find_all(attrs={"src": True})
        if link.get('src')
    ]
    return href_items


def not_found_expected_uri_items_in_web_page(
        expected_uri_items, web_page_uri_items):
    return set(expected_uri_items) - set(web_page_uri_items)


def check_website_uri_list(uri_list_file_path, website_url_list):
    """
    Verifica o acesso de cada item da `uri_list_file_path`
    Exemplo de seu conteúdo:
        /scielo.php?script=sci_serial&pid=0001-3765
        /scielo.php?script=sci_issues&pid=0001-3765
        /scielo.php?script=sci_issuetoc&pid=0001-376520200005
        /scielo.php?script=sci_arttext&pid=S0001-37652020000501101
    """
    Logger.debug("check_website_uri_list IN")

    if not website_url_list:
        raise ValueError(
            "Unable to check the Web site resources are available "
            "because no Website URL was informed")

    uri_list_items = read_file(uri_list_file_path)

    uri_list_items = concat_website_url_and_uri_list_items(
        website_url_list, uri_list_items)

    total = len(uri_list_items)
    Logger.info("Quantidade de URI: %i", total)
    unavailable_uri_items = check_uri_list(uri_list_items)

    if unavailable_uri_items:
        Logger.info(
            "Não encontrados (%i/%i):\n%s",
            len(unavailable_uri_items), total,
            "\n".join(unavailable_uri_items))
    else:
        Logger.info("Encontrados: %i/%i", total, total)

    Logger.debug("check_website_uri_list OUT")


def read_file(uri_list_file_path):
    with open(uri_list_file_path) as fp:
        uri_list_items = fp.read().splitlines()
    return uri_list_items


def concat_website_url_and_uri_list_items(website_url_list, uri_list_items):
    if not website_url_list or not uri_list_items:
        return []
    items = []
    for website_url in website_url_list:
        for uri in uri_list_items:
            if uri:
                items.append(str(website_url) + str(uri))
    return items


def check_uri_list(uri_list_items):
    """Acessa uma lista de URI e retorna as que falharam"""
    failures = []
    for uri in uri_list_items:
        if not access_uri(uri):
            failures.append(uri)
    return failures


def requests_get(uri, function=None):
    try:
        function = function or requests.head
        response = function(uri, timeout=10)
    except (requests.exceptions.ConnectionError,
            MaxRetryError,
            NewConnectionError) as e:
        Logger.error(
            "The URL '%s': %s",
            uri,
            e,
        )
        return False
    else:
        return response


def access_uri(uri, function=None):
    """Acessa uma URI e reporta o seu status de resposta"""
    function = function or requests.head
    response = requests_get(uri, function)
    if not response:
        return False

    if response.status_code in (200, 301, 302):
        return response

    if response.status_code in (429, 500, 502, 503, 504):
        return wait_and_retry_to_access_uri(uri, function)

    Logger.error(
        "The URL '%s' returned the status code '%s'.",
        uri,
        response.status_code,
    )
    return False


def retry_after():
    return (5, 10, 20, 40, 80, 160, 320, 640, )


def wait_and_retry_to_access_uri(uri, function=None):
    """
    Aguarda `t` segundos e tenta novamente até que status_code nao seja
    um destes (429, 500, 502, 503, 504)
    """
    function = function or requests.head
    available = False
    total_secs = 0
    for t in retry_after():
        Logger.info("Retry to access '%s' after %is", uri, t)
        total_secs += t
        time.sleep(t)

        response = requests_get(uri, function)

        if not response:
            available = False
            break

        if response.status_code in (429, 500, 502, 503, 504):
            continue

        if response.status_code in (200, 301, 302):
            available = response
        break

    Logger.info(
        "The URL '%s' returned the status code '%s' after %is",
        uri,
        response.status_code,
        total_secs
    )
    return available
