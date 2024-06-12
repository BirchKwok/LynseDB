import time
from datetime import datetime
from typing import Union, List, Tuple

import msgpack
import numpy as np
import httpx
import pandas as pd
from spinesUtils.asserts import raise_if
from tqdm import trange

from lynse.core_components.kv_cache.filter import Filter
from lynse.api import config, logger
from lynse.core_components.thread_safe_list import SafeList
from lynse.utils.utils import SearchResultsCache


class ExecutionError(Exception):
    pass


def raise_error_response(response):
    """
    Raise an error response.

    Parameters:
        response: The response from the server.

    Raises:
        ExecutionError: If the server returns an error.
    """
    try:
        rj = response.json()
        raise ExecutionError(rj)
    except Exception as e:
        print(e)
        raise ExecutionError(response.text)


def pack_data(data):
    """
    Pack the data.

    Parameters:
        data: The data to pack.

    Returns:
        bytes: The packed data.
    """
    packed_data = msgpack.packb(data, use_bin_type=True)
    return packed_data


class Collection:
    name = "Remote"

    def __init__(self, url, database_name, collection_name, **params):
        """
        Initialize the collection.
            .. versionadded:: 0.3.2

        Parameters:
            url (str): The URL of the server.
            database_name (str): The name of the database.
            collection_name (str): The name of the collection.
            **params: The collection parameters.
                - dim (int): The dimension of the vectors.
                - chunk_size (int): The chunk size.
                - distance (str): The distance metric.
                - dtypes (str): The data types.
                - use_cache (bool): Whether to use cache.
                - scaler_bits (int): The scaler bits.
                - n_threads (int): The number of threads.
                - warm_up (bool): Whether to warm up.
                - drop_if_exists (bool): Whether to drop the collection if it exists.
                - buffer_size (int): The buffer size.

        """
        self.IS_DELETED = False
        self._url = url
        self._database_name = database_name
        self._collection_name = collection_name
        self._session = httpx.Client(http2=True, timeout=120)
        self._init_params = params

        self.most_recent_search_report = {}
        self.search_report = {}

        self.COMMIT_FLAG = False

        self._mesosphere_list = SafeList()

    def _get_commit_msg(self):
        """
        Get the commit message.

        Returns:
            str: The last commit time.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self._url}/get_commit_msg'
        data = {"database_name": self._database_name, "collection_name": self._collection_name}

        response = self._session.post(url, json=data)

        rj = response.json()
        if response.status_code == 200:
            if (rj['params']['commit_msg'] is None or
                    rj['params']['commit_msg'] == 'No commit message found for this collection'):
                return None
            return rj['params']['commit_msg']['last_commit_time']
        else:
            raise ExecutionError(rj)

    def _update_commit_msg(self, last_commit_time):
        """
        Update the commit message.

        Parameters:
            last_commit_time (str): The last commit time.

        Returns:
            dict: The response from the server.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self._url}/update_commit_msg'
        data = {
            "database_name": self._database_name,
            "collection_name": self._collection_name,
            "last_commit_time": last_commit_time,
        }

        response = self._session.post(url, json=data)

        if response.status_code == 200:
            return response.json()
        else:
            try:
                rj = response.json()
                raise ExecutionError(rj)
            except Exception as e:
                print(e)
                raise ExecutionError(response.text)

    def _if_exists(self):
        """
        Check if the collection exists.

        Returns:
            bool: Whether the collection exists.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self._url}/is_collection_exists'
        data = {"database_name": self._database_name, "collection_name": self._collection_name}

        response = self._session.post(url, json=data)

        if response.status_code == 200:
            return response.json()['params']['exists']
        else:
            raise_error_response(response)

    def add_item(self, vector: Union[list[float], np.ndarray], id: int, *, field: Union[dict, None] = None,
                 normalize: bool = False, delay_num: int = 1000):
        """
        Add an item to the collection.
            .. versionadded:: 0.3.2

        Parameters:
            vector (list[float], np.ndarray): The vector of the item.
            id (int): The ID of the item.
            field (dict, optional): The fields of the item.
            normalize (bool): Whether to normalize the vector. Default is False.
            delay_num (int): Number of items to delay push. Default is 1000.

        Returns:
            int: The ID of the item. If delay_num is greater than 0, and the number of items added is less than delay_num,
                the function will return None. Otherwise, the function will return the IDs of the items added.

        Raises:
            ValueError: If the collection has been deleted or does not exist.
            ExecutionError: If the server returns an error.
        """
        raise_if(ValueError, (not isinstance(delay_num, int)) or delay_num < 0,
                 'The delay_num must be an integer and >= 0.')

        if delay_num == 0:
            url = f'{self._url}/add_item'

            headers = {'Content-Type': 'application/msgpack'}

            data = {
                "database_name": self._database_name,
                "collection_name": self._collection_name,
                "item": {
                    "vector": vector if isinstance(vector, list) else vector.tolist(),
                    "id": id if id is not None else None,
                    "field": field if field is not None else {},
                },
                "normalize": normalize
            }

            response = self._session.post(url, content=pack_data(data), headers=headers)

            if response.status_code == 200:
                self.COMMIT_FLAG = False
                return response.json()['params']['item']['id']
            else:
                raise_error_response(response)
        else:
            self._mesosphere_list.append({
                "vector": vector if isinstance(vector, list) else vector.tolist(),
                "id": id if id is not None else None,
                "field": field if field is not None else {},
            })

            if len(self._mesosphere_list) == delay_num:
                url = f'{self._url}/bulk_add_items'

                headers = {'Content-Type': 'application/msgpack'}

                data = {
                    "database_name": self._database_name,
                    "collection_name": self._collection_name,
                    "items": self._mesosphere_list,
                    "normalize": normalize
                }

                response = self._session.post(url, content=pack_data(data), headers=headers)

                if response.status_code == 200:
                    self.COMMIT_FLAG = False
                    self._mesosphere_list = self._mesosphere_list[delay_num:]
                else:
                    raise_error_response(response)

            return id

    @staticmethod
    def _check_bulk_add_items(vectors):
        items = []
        for vector in vectors:
            raise_if(TypeError, not isinstance(vector, tuple), 'Each item must be a tuple of vector, '
                                                               'ID, and fields(optional).')
            vec_len = len(vector)

            if vec_len == 3:
                v1, v2, v3 = vector
                items.append({
                    "vector": v1.tolist() if isinstance(v1, np.ndarray) else v1,
                    "id": v2,
                    "field": v3,
                })
            elif vec_len == 2:
                v1, v2 = vector
                items.append({
                    "vector": v1.tolist() if isinstance(v1, np.ndarray) else v1,
                    "id": v2,
                    "field": {},
                })
            else:
                raise TypeError('Each item must be a tuple of vector, ID, and fields(optional).')

        return items

    def bulk_add_items(
            self,
            vectors: List[Union[
                Tuple[Union[List, Tuple, np.ndarray], int, dict],
                Tuple[Union[List, Tuple, np.ndarray], int]
            ]],
            normalize: bool = False,
            batch_size: int = 1000,
            enable_progress_bar: bool = True
    ):
        """
        Add multiple items to the collection.
            .. versionadded:: 0.3.2

        Parameters:
            vectors (List[Tuple[Union[List, Tuple, np.ndarray], int, dict]],
            List[Tuple[Union[List, Tuple, np.ndarray], int]]):
                The list of items to add. Each item is a tuple containing the vector, ID, and fields.
            normalize (bool): Whether to normalize the vectors. Default is False.
            batch_size (int): The batch size. Default is 1000.
            enable_progress_bar (bool): Whether to enable the progress bar. Default is True.

        Returns:
            dict: The response from the server.

        Raises:
            ValueError: If the collection has been deleted or does not exist.
            TypeError: If the vectors are not in the correct format.
            ExecutionError: If the server returns an error.
        """

        url = f'{self._url}/bulk_add_items'
        total_batches = (len(vectors) + batch_size - 1) // batch_size

        ids = []

        if enable_progress_bar:
            iter_obj = trange(total_batches, desc='Adding items', unit='batch')
        else:
            iter_obj = range(total_batches)

        headers = {'Content-Type': 'application/msgpack'}

        for i in iter_obj:
            start = i * batch_size
            end = (i + 1) * batch_size
            items = vectors[start:end]

            items_after_checking = self._check_bulk_add_items(items)

            data = {
                "database_name": self._database_name,
                "collection_name": self._collection_name,
                "items": items_after_checking,
                "normalize": normalize
            }
            # Send request using session to keep the connection alive
            response = self._session.post(url, content=pack_data(data), headers=headers)

            if response.status_code == 200:
                self.COMMIT_FLAG = False
                ids.extend(response.json()['params']['ids'])
            else:
                raise_error_response(response)

        return ids

    def _rollback(self):
        self._mesosphere_list = SafeList()

    def commit(self):
        """
        Commit the changes in the collection.
            .. versionadded:: 0.3.2

        Returns:
            dict: The response from the server.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self._url}/commit'
        data = {"database_name": self._database_name, "collection_name": self._collection_name}

        if self._mesosphere_list:
            data["items"] = self._mesosphere_list

        response = self._session.post(url, content=pack_data(data), headers={'Content-Type': 'application/msgpack'})

        if self._mesosphere_list:
            self._mesosphere_list = SafeList()

        if response.status_code == 202:
            task_id = response.json().get('task_id')
            status_url = f'{self._url}/status/{task_id}'

            while True:
                status_response = self._session.get(status_url)
                status_data = status_response.json()

                if status_response.status_code == 200:
                    logger.info(f'Task status: {status_data}')
                    if status_data['status'] in ['Success', 'Error']:
                        if status_data['status'] == 'Success':
                            self._update_commit_msg(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                        return status_data
                else:
                    raise_error_response(status_response)

                time.sleep(2)
        else:
            raise_error_response(response)

    def build_index(self, index_mode: str = 'IVF-FLAT', n_clusters: int = 16):
        """
        Build the index of the collection.
            .. versionadded:: 0.3.6

        Parameters:
            index_mode (str): The index mode. Default is 'IVF-FLAT'.
            n_clusters (int): The number of clusters. Default is 16.

        Returns:
            dict: The response from the server.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self._url}/build_index'
        data = {
            "database_name": self._database_name,
            "collection_name": self._collection_name,
            "index_mode": index_mode,
            "n_clusters": n_clusters
        }

        response = self._session.post(url, json=data)

        if response.status_code == 200:
            return response.json()
        else:
            raise_error_response(response)

    def remove_index(self):
        """
        Remove the index of the collection.
            .. versionadded:: 0.3.6

        Returns:
            dict: The response from the server.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self._url}/remove_index'
        data = {"database_name": self._database_name, "collection_name": self._collection_name}
        response = self._session.post(url, json=data)

        if response.status_code == 200:
            return response.json()
        else:
            raise_error_response(response)

    def insert_session(self):
        """
        Start an insert session.
            .. versionadded:: 0.3.2
        """
        from lynse.execution_layer.session import DataOpsSession

        return DataOpsSession(self)

    @SearchResultsCache(config.LYNSE_SEARCH_CACHE_SIZE)
    def _search(self, vector: Union[list[float], np.ndarray], k: int = 10, distance: str = 'IP',
                search_filter: Union[Filter, None] = None, normalize=False, **kwargs):
        """
        Search the collection.
            .. versionadded:: 0.3.2

        Parameters:
            vector (list[float] or np.ndarray): The search vector.
            k (int): The number of results to return. Default is 10.
            distance (str): The distance metric. Default is 'IP', it can be 'cosine' or 'L2' or 'IP'.
            search_filter (Filter, optional): The field filter to apply to the search, must be a Filter object.
            normalize (bool): Whether to normalize the vector. Default is False.

        Returns:
            Tuple: The indices and similarity scores of the top k nearest vectors.

        Raises:
            ValueError: If the collection has been deleted or does not exist.
            ExecutionError: If the server returns an error.
        """
        url = f'{self._url}/search'

        if search_filter is not None:
            raise_if(TypeError, not isinstance(search_filter, Filter), 'The search filter must be a Filter object.')
            search_filter = search_filter.to_dict()

        data = {
            "database_name": self._database_name,
            "collection_name": self._collection_name,
            "vector": vector if isinstance(vector, list) else vector.tolist(),
            "k": k,
            'distance': distance,
            "search_filter": search_filter,
            "return_similarity": True,
            "normalize": normalize
        }
        response = self._session.post(url, json=data)

        if response.status_code == 200:
            return response.json()
        else:
            raise_error_response(response)

    def search(
            self, vector: Union[list[float], np.ndarray], k: int = 10, distance: str = 'IP',
            search_filter: Union[Filter, None] = None, return_similarity: bool = True,
            normalize: bool = False
    ):
        """
        Search the collection.
            .. versionadded:: 0.3.2

        Parameters:
            vector (list[float] or np.ndarray): The search vector.
            k (int): The number of results to return. Default is 10.
            distance (str): The distance metric. Default is 'IP'. It can be 'cosine' or 'L2' or 'IP'.
            search_filter (Filter, optional): The field filter to apply to the search, must be a Filter object.
            return_similarity (bool): Whether to return the similarity. Default is True.
            normalize (bool): Whether to normalize the vector. Default is False.

        Returns:
            Tuple: The indices and similarity scores of the top k nearest vectors.

        Raises:
            ValueError: If the collection has been deleted or does not exist.
            ExecutionError: If the server returns an error.
        """
        self.most_recent_search_report = {}

        tik = time.time()
        if self._init_params['use_cache']:
            rjson = self._search(vector=vector, k=k, distance=distance,
                                 search_filter=search_filter, return_similarity=return_similarity, normalize=normalize)
        else:
            rjson = self._search(vector=vector, k=k, distance=distance, search_filter=search_filter,
                                 return_similarity=return_similarity, now=time.time(), normalize=normalize)

        tok = time.time()

        self.most_recent_search_report['Collection Shape'] = self.shape
        self.most_recent_search_report['Search Time'] = rjson['params']['items']['search time']
        self.most_recent_search_report['Search Distance'] = rjson['params']['items']['distance']
        self.most_recent_search_report['Search K'] = k

        ids, scores = np.array(rjson['params']['items']['ids']), np.array(rjson['params']['items']['scores'])

        if ids is not None:
            self.most_recent_search_report[f'Top {k} Results ID'] = ids
            if return_similarity:
                self.most_recent_search_report[f'Top {k} Results Similarity'] = scores
            else:
                if f'Top {k} Results Similarity' in self.most_recent_search_report:
                    del self.most_recent_search_report[f'Top {k} Results Similarity']

        self.most_recent_search_report['Search Time'] = f"{tok - tik :>.5f} s"

        if return_similarity:
            return ids, scores

        return ids, None

    @property
    def shape(self):
        """
        Get the shape of the collection.
            .. versionadded:: 0.3.2

        Returns:
            Tuple: The shape of the collection.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self._url}/collection_shape'
        data = {"database_name": self._database_name, "collection_name": self._collection_name}
        response = self._session.post(url, json=data)

        if response.status_code == 200:
            return tuple(response.json()['params']['shape'])
        else:
            rj = response.json()
            if 'error' in rj and rj['error'] == f"Collection '{self._collection_name}' does not exist.":
                return 0, self._init_params['dim']
            else:
                raise_error_response(response)

    def head(self, n: int = 5):
        """
        Get the first n items in the collection.
            .. versionadded:: 0.3.6

        Parameters:
            n (int): The number of items to return. Default is 5.

        Returns:
            pd.DataFrame: The first n items in the collection.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self._url}/head'
        data = {"database_name": self._database_name, "collection_name": self._collection_name, "n": n}
        response = self._session.post(url, json=data)

        if response.status_code == 200:
            head = response.json()['params']['head']
            return np.asarray(head[0]), np.asarray(head[1])
        else:
            raise_error_response(response)

    def tail(self, n: int = 5):
        """
        Get the last n items in the collection.
            .. versionadded:: 0.3.6

        Parameters:
            n (int): The number of items to return. Default is 5.

        Returns:
            pd.DataFrame: The last n items in the collection.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self._url}/tail'
        data = {"database_name": self._database_name, "collection_name": self._collection_name, "n": n}
        response = self._session.post(url, json=data)

        if response.status_code == 200:
            tail = response.json()['params']['tail']
            return np.asarray(tail[0]), np.asarray(tail[1])
        else:
            raise_error_response(response)

    @property
    def search_report_(self):
        """
        Get the search report of the collection.
            .. versionadded:: 0.3.2

        Returns:
            str: The search report.
        """
        report = '\n* - MOST RECENT SEARCH REPORT -\n'
        for key, value in self.most_recent_search_report.items():
            if key == "Collection Shape":
                value = self.shape

            report += f'| - {key}: {value}\n'

        return report

    def update_description(self, description: str):
        """
        Update the description of the collection.
            .. versionadded:: 0.3.4

        Parameters:
            description (str): The description of the collection.

        Returns:
            dict: The response from the server.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self._url}/update_description'
        data = {
            "database_name": self._database_name,
            "collection_name": self._collection_name,
            "description": description
        }

        response = self._session.post(url, json=data)

        if response.status_code == 200:
            return response.json()
        else:
            raise_error_response(response)

    def get_collection_path(self):
        """
        Get the path of the database.
            .. versionadded:: 0.3.6

        Returns:
            str: The path of the database.
        """
        url = f'{self._url}/get_collection_path'
        data = {"database_name": self._database_name, "collection_name": self._collection_name}

        response = self._session.post(url, json=data)

        if response.status_code == 200:
            return response.json()['params']['collection_path']
        else:
            raise_error_response(response)

    def __repr__(self):
        if self.status_report_['COLLECTION STATUS REPORT']['Collection status'] == 'DELETED':
            title = "Deleted Convergence collection with status: \n"
        else:
            title = "Convergence collection with status: \n"

        report = '\n* - COLLECTION STATUS REPORT -\n'
        for key, value in self.status_report_['COLLECTION STATUS REPORT'].items():
            report += f'| - {key}: {value}\n'

        return title + report

    def __str__(self):
        return self.__repr__()

    @property
    def status_report_(self):
        """
        Return the database report.

        Returns:
            dict: The database report.

        Raises:
            ExecutionError: If the server returns an error.
        """
        name = "Collection"

        url = f'{self._url}/is_collection_exists'
        data = {"database_name": self._database_name, "collection_name": self._collection_name}
        response = self._session.post(url, json=data)

        if response.status_code != 200:
            raise_error_response(response)

        is_exists = response.json()['params']['exists']

        last_commit_time = self._get_commit_msg()
        db_report = {f'{name.upper()} STATUS REPORT': {
            f'{name} shape': (0, self._init_params['dim']) if self.IS_DELETED else self.shape,
            f'{name} last_commit_time': last_commit_time,
            f'{name} distance': self._init_params['distance'],
            f'{name} use_cache': self._init_params['use_cache'],
            f'{name} status': 'DELETED' if self.IS_DELETED or not is_exists else 'ACTIVE'
        }}

        return db_report


class HTTPClient:
    def __init__(self, url, database_name):
        """
        Initialize the client.
            .. versionadded:: 0.3.2

        Parameters:
            url (str): The URL of the server, must start with "http://" or "https://".
            database_name (str): The name of the database.

        Raises:
            TypeError: If the URL is not a string.
            ValueError: If the URL does not start with "http://" or "https://".
            ConnectionError: If the server cannot be connected to.
        """

        raise_if(TypeError, not isinstance(url, str), 'The URL must be a string.')
        raise_if(ValueError, not url.startswith('http://') or url.startswith('https://'),
                 'The URL must start with "http://" or "https://".')

        self._session = httpx.Client()

        if url.endswith('/'):
            self.url = url[:-1]
        else:
            self.url = url

        self.database_name = database_name

    def require_collection(
            self,
            collection: str,
            dim: int = None,
            chunk_size: int = 100_000,
            distance: str = 'cosine',
            dtypes: str = 'float32',
            use_cache: bool = True,
            scaler_bits: Union[int, None] = 8,
            n_threads: Union[int, None] = 10,
            warm_up: bool = False,
            drop_if_exists: bool = False,
            description: str = None,
            buffer_size: int = 20
    ):
        """
        Create a collection.
            .. versionadded:: 0.3.2

        Parameters:
            collection (str): The name of the collection.
            dim (int): The dimension of the vectors. Default is None.
                When creating a new collection, the dimension of the vectors must be specified.
                When loading an existing collection, the dimension of the vectors is automatically loaded.
            chunk_size (int): The chunk size. Default is 100,000.
            distance (str): The distance metric. Default is 'cosine'.
            dtypes (str): The data types. Default is 'float32'.
            use_cache (bool): Whether to use cache. Default is True.
            scaler_bits (int): The scaler bits. Default is 8.
            n_threads (int): The number of threads. Default is 10.
            warm_up (bool): Whether to warm up. Default is False.
            drop_if_exists (bool): Whether to drop the collection if it exists. Default is False.
            description (str): A description of the collection. Default is None.
                The description is limited to 500 characters.
                    .. versionadded:: 0.3.4
            buffer_size (int): The buffer size. Default is 20.
                .. versionadded:: 0.3.6

        Returns:
            Collection: The collection object.

        Raises:
            ConnectionError: If the server cannot be connected to.
        """
        url = f'{self.url}/required_collection'

        data = {
            "database_name": self.database_name,
            "collection_name": collection,
            "dim": dim,
            "chunk_size": chunk_size,
            "distance": distance,
            "dtypes": dtypes,
            "use_cache": use_cache,
            "scaler_bits": scaler_bits,
            "n_threads": n_threads,
            "warm_up": warm_up,
            "drop_if_exists": drop_if_exists,
            "description": description,
            "buffer_size": buffer_size
        }

        try:
            response = self._session.post(url, json=data)
            if response.status_code == 200:
                del data['collection_name']
                del data['database_name']
                collection = Collection(url=self.url, database_name=self.database_name,
                                        collection_name=collection, **data)
                collection._search.clear_cache()
                return collection
            else:
                raise_error_response(response)
        except httpx.RequestError:
            raise ConnectionError(f'Failed to connect to the server at {url}.')

    def get_collection(self, collection: str, buffer_size=10, warm_up=True):
        """
        Get a collection.
            .. versionadded:: 0.3.2

        Parameters:
            collection (str): The name of the collection.
            buffer_size (int): The buffer size. Default is 10.
                .. versionadded:: 0.3.6
            warm_up (bool): Whether to warm up. Default is True.
                .. versionadded:: 0.3.6

        Returns:
            Collection: The collection object.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self.url}/is_collection_exists'
        data = {"database_name": self.database_name, "collection_name": collection}
        response = self._session.post(url, json=data)

        if response.status_code == 200 and response.json()['params']['exists']:
            url = f'{self.url}/get_collection_config'
            data = {"database_name": self.database_name, "collection_name": collection}
            response = self._session.post(url, json=data)

            params = response.json()['params']['config']
            params.update({'buffer_size': buffer_size, 'warm_up': warm_up})

            return Collection(url=self.url, database_name=self.database_name, collection_name=collection,
                              **params)
        else:
            raise_error_response(response)

    def drop_collection(self, collection: str):
        """
        Drop a collection.
            .. versionadded:: 0.3.2

        Parameters:
            collection (str): The name of the collection.

        Returns:
            dict: The response from the server.

        Raises:
            ExecutionError: If the server returns an error.
        """
        try:
            _ = self.get_collection(collection)
            _._search.clear_cache()
        except ExecutionError:
            pass

        url = f'{self.url}/drop_collection'
        data = {"database_name": self.database_name, "collection_name": collection}
        return self._session.post(url, json=data).json()

    def drop_database(self):
        """
        Drop the database.
            .. versionadded:: 0.3.2

        Returns:
            dict: The response from the server.

        Raises:
            ExecutionError: If the server returns an error.
        """
        if not self.database_exists()['params']['exists']:
            return {'status': 'success', 'message': 'The database does not exist.'}

        url = f'{self.url}/drop_database'
        data = {"database_name": self.database_name}
        response = self._session.post(url, json=data)

        if response.status_code == 200:
            return response.json()
        else:
            raise_error_response(response)

    def database_exists(self):
        """
        Check if the database exists.
            .. versionadded:: 0.3.2

        Returns:
            dict: The response from the server.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self.url}/database_exists'
        data = {"database_name": self.database_name}
        response = self._session.post(url, json=data)

        if response.status_code == 200:
            return response.json()
        else:
            raise_error_response(response)

    def show_collections(self):
        """
        Show all collections in the database.
            .. versionadded:: 0.3.2

        Returns:
            List: The list of collections.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self.url}/show_collections'
        data = {"database_name": self.database_name}
        response = self._session.post(url, json=data)

        if response.status_code == 200:
            return response.json()['params']['collections']
        else:
            raise_error_response(response)

    def set_environment(self, env: dict):
        """
        Set the environment variables.
            .. versionadded:: 0.3.2

        Parameters:
            env (dict): The environment variables. It can be specified on the same time or separately.
                - LYNSE_LOG_LEVEL: The log level.
                - LYNSE_LOG_PATH: The log path.
                - LYNSE_TRUNCATE_LOG: Whether to truncate the log.
                - LYNSE_LOG_WITH_TIME: Whether to log with time.
                - LYNSE_KMEANS_EPOCHS: The number of epochs for KMeans.
                - LYNSE_SEARCH_CACHE_SIZE: The search cache size.
                - LYNSE_DATALOADER_BUFFER_SIZE: The dataloader buffer size.

        Returns:
            dict: The response from the server.

        Raises:
            TypeError: If the value of an environment variable is not a string.
            ExecutionError: If the server returns an error.
        """
        url = f'{self.url}/set_environment'

        env_list = ['LYNSE_LOG_LEVEL', 'LYNSE_LOG_PATH', 'LYNSE_TRUNCATE_LOG', 'LYNSE_LOG_WITH_TIME',
                    'LYNSE_KMEANS_EPOCHS', 'LYNSE_SEARCH_CACHE_SIZE', 'LYNSE_DATALOADER_BUFFER_SIZE']

        data = {"database_name": self.database_name}
        for key in env:
            if key in env_list:
                raise_if(TypeError, not isinstance(env[key], str), f'The value of {key} must be a string.')
                data[key] = env[key]

        response = self._session.post(url, json=data)

        if response.status_code == 200:
            return response.json()
        else:
            raise_error_response(response)

    def get_environment(self):
        """
        Get the environment variables.
            .. versionadded:: 0.3.2

        Returns:
            dict: The response from the server.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self.url}/get_environment'
        data = {"database_name": self.database_name}
        response = self._session.post(url, json=data)

        if response.status_code == 200:
            return response.json()
        else:
            raise_error_response(response)

    def update_collection_description(self, collection: str, description: str):
        """
        Update the description of a collection.
            .. versionadded:: 0.3.4

        Parameters:
            collection (str): The name of the collection.
            description (str): The description of the collection.

        Returns:
            dict: The response from the server.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self.url}/update_collection_description'
        data = {"database_name": self.database_name, "collection_name": collection, "description": description}
        response = self._session.post(url, json=data)

        if response.status_code == 200:
            return response.json()
        else:
            raise_error_response(response)

    def show_collections_details(self):
        """
        Show all collections in the database with details.
            .. versionadded:: 0.3.4

        Returns:
            pandas.DataFrame: The details of the collections.

        Raises:
            ExecutionError: If the server returns an error.
        """
        url = f'{self.url}/show_collections_details'
        data = {"database_name": self.database_name}
        response = self._session.post(url, json=data)

        if response.status_code == 200:
            rj = response.json()['params']['collections']
            rj_df = pd.DataFrame(rj)
            rj_df.index.name = 'collections'
            return rj_df
        else:
            raise_error_response(response)

    def __repr__(self):
        if self.database_exists()['params']['exists']:
            return f'Convergence HTTP Client connected to {self.url}, use database: `{self.database_name}`.'
        else:
            return f"Database `{self.database_name}` does not exist on the Convergence remote server."

    def __str__(self):
        return self.__repr__()