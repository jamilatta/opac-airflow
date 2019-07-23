import os
import http.client
import shutil
import tempfile
from unittest import TestSuite, TestCase, TestLoader, TextTestRunner
from unittest.mock import patch, Mock, MagicMock

from airflow import DAG
from lxml import etree

from kernel_documents import (
    get_sps_packages,
    list_documents,
    documents_to_delete,
    delete_documents,
)


XML_FILE_CONTENT = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Publishing DTD v1.0 20120330//EN" "JATS-journalpublishing1.dtd">
<article article-type="research-article" dtd-version="1.0" specific-use="sps-1.5" xml:lang="en" xmlns:mml="http://www.w3.org/1998/Math/MathML" xmlns:xlink="http://www.w3.org/1999/xlink">
    <article-meta>
        <article-id pub-id-type="publisher-id" specific-use="scielo">FX6F3cbyYmmwvtGmMB7WCgr</article-id>
    </article-meta>
</article>
"""


class TestGetSPSPackages(TestCase):
    @patch('kernel_documents.Variable.get')
    def test_get_sps_packages_raises_error_if_no_xc_dir_from_variable(self,
                                                                      mk_variable_get):
        mk_variable_get.side_effect = KeyError
        self.assertRaises(KeyError, get_sps_packages)

    @patch('kernel_documents.Path')
    @patch('kernel_documents.Variable.get')
    @patch('kernel_documents.open')
    def test_get_sps_packages_gets_xc_dir_from_variable(self, mk_open,
                                                        mk_variable_get,
                                                        MockPath):

        mk_variable_get.side_effect = ["dir/path/scilista.lst",
                                       "dir/source",
                                       "dir/destination"]
        kwargs = {
            "ti": MagicMock(),
        }
        get_sps_packages(**kwargs)
        MockPath.assert_any_call("dir/source")
        MockPath.assert_any_call("dir/destination")

    @patch('kernel_documents.shutil')
    @patch('kernel_documents.Variable.get')
    @patch('kernel_documents.open')
    def test_get_sps_packages_moves_from_xc_dir_if_xc_source_exists(self,
                                                                    mk_open,
                                                                    mk_variable_get,
                                                                    mk_shutil):
        mk_variable_get.return_value = ""
        kwargs = {
            "ti": MagicMock(),
        }
        get_sps_packages(**kwargs)
        mk_shutil.move.assert_not_called()

    @patch('kernel_documents.shutil')
    @patch('kernel_documents.os.path.exists')
    @patch('kernel_documents.Variable.get')
    @patch('kernel_documents.open')
    def test_get_sps_packages_moves_from_xc_dir_to_proc_dir(self,
                                                            mk_open,
                                                            mk_variable_get,
                                                            mk_path_exists,
                                                            mk_shutil):
        mk_path_exists.return_value = True
        mk_open.return_value.__enter__.return_value.readlines.return_value = [
            "rba v53n1",
        ]

        with tempfile.TemporaryDirectory() as tmpdirname:
            test_paths = [
                "dir/path/scilista.lst",
                "../fixtures",
                tmpdirname,
            ]
            mk_variable_get.side_effect = test_paths
            kwargs = {
                "ti": MagicMock(),
            }
            get_sps_packages(**kwargs)
            mk_shutil.move.assert_called_once_with(
                "../fixtures/rba_v53n1.zip",
                tmpdirname + "/rba_v53n1.zip"
            )

    @patch('kernel_documents.shutil')
    @patch('kernel_documents.os.path.exists')
    @patch('kernel_documents.Variable.get')
    @patch('kernel_documents.open')
    def test_get_sps_packages_calls_ti_xcom_push_with_empty_list(
        self, mk_open, mk_variable_get, mk_path_exists, mk_shutil
    ):
        mk_path_exists.return_value = False
        mk_variable_get.return_value = ""
        kwargs = {
            "scilista": ["rba v53n1"],
            "ti": MagicMock(),
        }
        get_sps_packages(**kwargs)
        kwargs["ti"].xcom_push.assert_called_once_with(
            key="sps_packages",
            value=[]
        )

    @patch('kernel_documents.shutil')
    @patch('kernel_documents.os.path.exists')
    @patch('kernel_documents.Variable.get')
    @patch('kernel_documents.open')
    def test_get_sps_packages_calls_ti_xcom_push_with_sps_packages_list(
        self, mk_open, mk_variable_get, mk_path_exists, mk_shutil
    ):
        mk_path_exists.return_value = True
        mk_variable_get.return_value = "dir/destination/"
        mk_open.return_value.__enter__.return_value.readlines.return_value = [
            "rba v53n1",
            "rba 2018nahead",
            "rsp v10n2-3",
            "abc v50"
        ]
        kwargs = {
            "ti": MagicMock()
        }
        get_sps_packages(**kwargs)
        kwargs["ti"].xcom_push.assert_called_once_with(
            key="sps_packages",
            value=[
                "dir/destination/abc_v50.zip",
                "dir/destination/rba_2018nahead.zip",
                "dir/destination/rba_v53n1.zip",
                "dir/destination/rsp_v10n2-3.zip",
            ]
        )

    @patch('kernel_documents.open')
    @patch('kernel_documents.Variable.get')
    def test_read_scilista_from_file(self, mk_variable_get, mk_open):
        mk_variable_get.return_value = "dir/path/scilista.lst"
        kwargs = {
            "ti": MagicMock()
        }
        get_sps_packages(**kwargs)
        mk_open.assert_called_once_with("dir/path/scilista.lst")


class TestListDocuments(TestCase):
    def test_list_document_gets_ti_sps_packages_list(self):
        kwargs = {"ti": MagicMock()}
        list_documents(**kwargs)
        kwargs["ti"].xcom_pull.assert_called_once_with(
            key="sps_packages",
            task_ids="get_sps_packages_id"
        )

    @patch('kernel_documents.ZipFile')
    def test_list_document_empty_ti_sps_packages_list(self, MockZipFile):
        kwargs = {"ti": MagicMock()}
        kwargs["ti"].xcom_pull.return_value = None
        list_documents(**kwargs)
        MockZipFile.assert_not_called()
        kwargs["ti"].xcom_push.assert_not_called()

    @patch('kernel_documents.ZipFile')
    def test_list_document_opens_all_zips(self, MockZipFile):
        sps_packages = [
            "dir/destination/abc_v50.zip",
            "dir/destination/rba_v53n1.zip",
            "dir/destination/rsp_v10n2-3.zip",
        ]
        kwargs = {"ti": MagicMock()}
        kwargs["ti"].xcom_pull.return_value = sps_packages
        list_documents(**kwargs)
        for sps_package in sps_packages:
            MockZipFile.assert_any_call(sps_package)

    @patch('kernel_documents.ZipFile')
    def test_list_document_reads_all_xmls_from_all_zips(self, MockZipFile):
        sps_packages = [
            "dir/destination/abc_v50.zip",
            "dir/destination/rba_v53n1.zip",
        ]
        sps_packages_file_lists = [
            [
                '0123-4567-abc-50-1-8.xml',
                'v53n1a01.pdf',
                '0123-4567-abc-50-1-8-gpn1a01t1.htm',
                '0123-4567-abc-50-1-8-gpn1a01g1.htm',
                '0123-4567-abc-50-9-18.xml',
                'v53n1a02.pdf',
            ],
            [
                '1806-907X-rba-53-01-1-8.xml',
                'v53n1a01.pdf',
                '1806-907X-rba-53-01-1-8-gpn1a01t1.htm',
                '1806-907X-rba-53-01-1-8-gpn1a01g1.htm',
                '1806-907X-rba-53-01-9-18.xml',
                'v53n1a02.pdf',
                '1806-907X-rba-53-01-19-25.xml',
                '1806-907X-rba-53-01-19-25-g1.jpg',
                'v53n1a03.pdf',
            ],
        ]
        kwargs = {"ti": MagicMock()}
        kwargs["ti"].xcom_pull.return_value = sps_packages
        MockZipFile.return_value.__enter__.return_value.namelist.side_effect = \
            sps_packages_file_lists
        list_documents(**kwargs)
        kwargs["ti"].xcom_push.assert_called_once_with(
            key="sps_packages_xmls",
            value={
                'dir/destination/abc_v50.zip': [
                    '0123-4567-abc-50-1-8.xml',
                    '0123-4567-abc-50-9-18.xml'
                ],
                'dir/destination/rba_v53n1.zip': [
                    '1806-907X-rba-53-01-1-8.xml',
                    '1806-907X-rba-53-01-9-18.xml',
                    '1806-907X-rba-53-01-19-25.xml']
            }
        )

    @patch('kernel_documents.ZipFile')
    def test_list_document_doesnt_call_ti_xcom_push_if_no_xml_files(self, MockZipFile):
        sps_packages = [
            "dir/destination/rba_v53n1.zip",
        ]
        sps_packages_file_list = [
            'v53n1a01.pdf',
            'v53n1a02.pdf',
            'v53n1a03.pdf',
        ]
        kwargs = {"ti": MagicMock()}
        kwargs["ti"].xcom_pull.return_value = sps_packages
        MockZipFile.return_value.__enter__.return_value.namelist.return_value = \
            sps_packages_file_list
        list_documents(**kwargs)
        kwargs["ti"].xcom_push.assert_not_called()


class TestDocumentsToDelete(TestCase):

    @patch('kernel_documents.ZipFile')
    def test_documents_to_delete_opens_zip(self, MockZipFile):
        documents_to_delete('dir/destination/abc_v50.zip', [])
        MockZipFile.assert_any_call('dir/destination/abc_v50.zip')

    @patch('kernel_documents.ZipFile')
    def test_documents_to_delete_reads_each_xml_from_each_zips(self, MockZipFile):
        sps_xml_files = [
            '0123-4567-abc-50-1-8.xml',
            '0123-4567-abc-50-9-18.xml'
        ]
        MockZipFile.return_value.__enter__.return_value.read.return_value = b""
        documents_to_delete('dir/destination/abc_v50.zip', sps_xml_files)
        for sps_xml_file in sps_xml_files:
            with self.subTest(sps_xml_file=sps_xml_file):
                for sps_xml_file in sps_xml_files:
                    MockZipFile.return_value.__enter__.return_value.read.assert_any_call(
                        sps_xml_file
                    )

    @patch('kernel_documents.ZipFile')
    def test_documents_to_delete_returns_empty_list_if_no_docs_to_delete(self, MockZipFile):
        xml_file = etree.tostring(etree.XML(XML_FILE_CONTENT))
        MockZipFile.return_value.__enter__.return_value.read.return_value = xml_file
        result = documents_to_delete(
            'dir/destination/abc_v50.zip', ['1806-907X-rba-53-01-1-8.xml']
        )
        self.assertEqual(result, [])

    @patch('kernel_documents.ZipFile')
    def test_documents_to_delete_returns_documents_id_to_delete(self, MockZipFile):
        article_id = etree.Element("article-id")
        article_id.set("specific-use", "delete")
        xml_file = etree.XML(XML_FILE_CONTENT)
        am_tag = xml_file.find(".//article-meta")
        am_tag.append(article_id)
        deleted_xml_file = etree.tostring(xml_file)
        MockZipFile.return_value.__enter__.return_value.read.return_value = deleted_xml_file
        result = documents_to_delete(
            'dir/destination/abc_v50.zip', ['1806-907X-rba-53-01-1-8.xml']
        )
        self.assertEqual(result, ["FX6F3cbyYmmwvtGmMB7WCgr"])   # SciELO ID de XML_FILE_CONTENT

    @patch('kernel_documents.logging')
    @patch('kernel_documents.ZipFile')
    def test_documents_to_delete_logs_error_if_no_scielo_id_in_doc_to_delete(
        self, MockZipFile, mk_logging
    ):
        article_id = etree.Element("article-id")
        article_id.set("specific-use", "delete")
        xml_file = etree.XML(XML_FILE_CONTENT)
        am_tag = xml_file.find(".//article-meta")
        am_tag.append(article_id)
        am_scielo_id = xml_file.find(".//article-id[@specific-use='scielo']")
        am_tag.remove(am_scielo_id)
        deleted_xml_file = etree.tostring(xml_file)
        print('\n', deleted_xml_file, '\n')
        MockZipFile.return_value.__enter__.return_value.read.return_value = deleted_xml_file
        documents_to_delete(
            'dir/destination/abc_v50.zip', ['1806-907X-rba-53-01-1-8.xml']
        )
        mk_logging.info.assert_any_call(
            'Cannot read SciELO ID from "1806-907X-rba-53-01-1-8.xml": '
            'missing element in XML'
        )


class TestDeleteDocuments(TestCase):
    def test_delete_documents_gets_ti_xcom_info(self):
        kwargs = {"ti": MagicMock()}
        delete_documents(**kwargs)
        kwargs["ti"].xcom_pull.assert_called_once_with(
            key="sps_packages_xmls",
            task_ids="list_documents_id"
        )

    @patch('kernel_documents.documents_to_delete')
    def test_delete_documents_empty_ti_xcom_info(self, mk_documents_to_delete):
        kwargs = {"ti": MagicMock()}
        kwargs["ti"].xcom_pull.return_value = None
        delete_documents(**kwargs)
        mk_documents_to_delete.assert_not_called()
        kwargs["ti"].xcom_push.assert_not_called()

    @patch('kernel_documents.documents_to_delete')
    def test_delete_documents_calls_documents_to_delete(
        self, mk_documents_to_delete
    ):
        sps_packages_xmls = {
            'dir/destination/abc_v50.zip': [
                '0123-4567-abc-50-1-8.xml',
                '0123-4567-abc-50-9-18.xml'
            ],
            'dir/destination/rba_v53n1.zip': [
                '1806-907X-rba-53-01-1-8.xml',
                '1806-907X-rba-53-01-9-18.xml',
                '1806-907X-rba-53-01-19-25.xml']
        }
        kwargs = {"ti": MagicMock()}
        kwargs["ti"].xcom_pull.return_value = sps_packages_xmls
        delete_documents(**kwargs)
        for sps_package, sps_xml_files in sps_packages_xmls.items():
            with self.subTest(sps_package=sps_package):
                mk_documents_to_delete.assert_any_call(sps_package, sps_xml_files)

    @patch('kernel_documents.kernel_connect')
    @patch('kernel_documents.logging')
    @patch('kernel_documents.documents_to_delete')
    def test_delete_documents_calls_kernel_connect_with_docs_to_delete(
        self, mk_documents_to_delete, mk_logging, mk_kernel_connect
    ):
        sps_packages_xmls = {
            'dir/destination/abc_v50.zip': [
                '0123-4567-abc-50-1-8.xml',
                '0123-4567-abc-50-9-18.xml'
            ],
            'dir/destination/rba_v53n1.zip': [
                '1806-907X-rba-53-01-1-8.xml',
                '1806-907X-rba-53-01-9-18.xml',
                '1806-907X-rba-53-01-19-25.xml']
        }
        docs_to_delete = [
            "FX6F3cbyYmmwvtGmMB7WCgr",
            "GZ5K2cbyYmmwvtGmMB71243",
            "KU890cbyYmmwvtGmMB7JUk4",
        ]
        kwargs = {"ti": MagicMock()}
        kwargs["ti"].xcom_pull.return_value = sps_packages_xmls
        mk_documents_to_delete.side_effect = [[docs_to_delete[0]], docs_to_delete[1:]]
        mk_kernel_connect.return_value = Mock(status_code=http.client.NO_CONTENT)
        delete_documents(**kwargs)
        for doc_to_delete in docs_to_delete:
            with self.subTest(doc_to_delete=doc_to_delete):
                mk_kernel_connect.assert_any_call(
                    "/documents/" + doc_to_delete,
                    "DELETE"
                )
                mk_logging.info.assert_any_call(
                    "Document %s deleted from kernel status: %d"
                    % (doc_to_delete, http.client.NO_CONTENT)
                )

    @patch('kernel_documents.kernel_connect')
    @patch('kernel_documents.logging')
    @patch('kernel_documents.documents_to_delete')
    def test_delete_documents_logs_error_if_kernel_connect_error(
        self, mk_documents_to_delete, mk_logging, mk_kernel_connect
    ):
        sps_packages_xmls = {
            'dir/destination/rba_v53n1.zip': [
                '1806-907X-rba-53-01-1-8.xml',
            ]
        }
        kwargs = {"ti": MagicMock()}
        kwargs["ti"].xcom_pull.return_value = sps_packages_xmls
        mk_documents_to_delete.return_value = ["FX6F3cbyYmmwvtGmMB7WCgr"]
        mk_kernel_connect.return_value = Mock(status_code=http.client.NOT_FOUND)
        delete_documents(**kwargs)
        mk_logging.info.assert_any_call(
            "Document %s not found in kernel: %d"
            % ("FX6F3cbyYmmwvtGmMB7WCgr", http.client.NOT_FOUND)
        )


if __name__ == '__main__':
    test_classes_to_run = [
        TestGetSPSPackages,
        TestListDocuments,
    ]

    loader = TestLoader()
    suites_list = [
        loader.loadTestsFromTestCase(test_class)
        for test_class in test_classes_to_run
    ]
    TextTestRunner().run(TestSuite(suites_list))
