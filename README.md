# MinVectorDB


<b>MinVectorDB</b> is a simple vector storage and query database implementation, providing clear and concise Python APIs aimed at lowering the barrier to using vector databases. More practical features will be added in the future. 

It is important to note that MinVectorDB is not designed for efficiency and thus does not include built-in algorithms like approximate nearest neighbors for efficient searching. 

It originated from the author's need to demonstrate a large language model demo, designed for 100% recall. 

Additionally, it has not undergone rigorous code testing, so caution is advised when using it in a production environment.
<br>
<b>MinVectorDB</b> 是简易实现的向量存储和查询数据库，提供简洁明了的python API，旨在降低向量数据库的使用门槛。未来将添加更多实用功能。

需要注意的是，MinVectorDB并非为追求效率而生，因此，并没有内置近似最近邻等高效查找算法。

它起源于作者需要演示大语言模型Demo的契机，为了追求100%召回率而设计，此外，也没有经过严格的代码测试，因此如果将其用于生产环境需要特别谨慎。

## Install

```shell
pip install MinVectorDB
```

## Qucik Start

### Sequentially add vectors.


```python
try:
    from IPython.display import display_markdown
except ImportError:
    def display_markdown(text, raw=True):
        print(text)

import numpy as np

from spinesUtils.utils import Timer
from min_vec import MinVectorDB

timer = Timer()



# ===================================================================
# ========================= DEMO 1 ==================================
# ===================================================================
# Demo 1 -- Sequentially add vectors.
# Create a MinVectorDB instance.
display_markdown("*Demo 1* -- **Sequentially add vectors**", raw=True)

timer.start()
db = MinVectorDB(dim=1024, database_path='test_min_vec.mvdb', chunk_size=1000)

np.random.seed(23)

def get_test_vectors(shape):
    for i in range(shape[0]):
        yield np.random.random(shape[1])

# Use automatic commit statements. Recommended.
with db.insert_session():
    # Define the initial ID.
    id = 0
    for t in get_test_vectors((10000, 1024)):
        # Vectors need to be normalized before writing to the database.
        # t = t / np.linalg.norm(t) 
        # Here, normalization can be directly specified, achieving the same effect as the previous sentence.
        db.add_item(t, id=id, normalize=True)
        
        # ID increments by 1 with each loop iteration.
        id += 1

# Or use manual commit statements.
# id = 0
# for t in get_test_vectors((10000, 1024)):
#     # Vectors need to be normalized before writing to the database.
#     # t = t / np.linalg.norm(t) 
#     # Here, normalization can be directly specified, achieving the same effect as the previous sentence.
#     db.add_item(t, id=id, normalize=True)
#     
#     # ID increments by 1 with each loop iteration.
#     id += 1
# db.commit()
        
print(f"\n* [Insert data] Time cost {timer.last_timestamp_diff():>.4f} s.")
timer.middle_point()

res = db.query(db.head(10)[0], k=10)
print("  - Query vector: ", db.head(10)[0])
print("  - Database index of top 10 results: ", res[0])
print("  - Cosine similarity of top 10 results: ", res[1])
print(f"\n* [Query data] Time cost {timer.last_timestamp_diff():>.4f} s.")
timer.end()



# This sentence is for demo demonstration purposes, to clear the currently created .mvdb files from the database, but this is optional in actual use.
db.delete()
```


*Demo 1* -- **Sequentially add vectors**


    
    * [Insert data] Time cost 6.9145 s.
      - Query vector:  [0.02898663 0.05306277 0.04289231 ... 0.0143056  0.01658325 0.04808333]
      - Database index of top 10 results:  [   0 5788  842  202 6658  396 5116 9447 1245 2393]
      - Cosine similarity of top 10 results:  [1.         0.77570757 0.77242908 0.77178528 0.77165615 0.77129891
     0.77062634 0.77019239 0.76990888 0.76983951]
    
    * [Query data] Time cost 0.0320 s.


### Bulk add vectors


```python
try:
    from IPython.display import display_markdown
except ImportError:
    def display_markdown(text, raw=True):
        print(text)

import numpy as np

from spinesUtils.utils import Timer
from min_vec import MinVectorDB

timer = Timer()

# ===================================================================
# ========================= DEMO 2 ==================================
# ===================================================================
# Demo 2 -- Bulk add vectors.
display_markdown("*Demo 2* -- **Bulk add vectors**", raw=True)
# print("# This is the demonstration area for Demo 2 -- Bulk add vectors.")

timer.start()

db = MinVectorDB(dim=1024, database_path='test_min_vec.mvdb', chunk_size=10000)

np.random.seed(23)

def get_test_vectors(shape):
    for i in range(shape[0]):
        yield np.random.random(shape[1])

with db.insert_session():  
    # Define the initial ID.
    id = 0
    vectors = []
    for t in get_test_vectors((100000, 1024)):
        # Vectors need to be normalized before writing to the database.
        # t = t / np.linalg.norm(t) 
        vectors.append((t, id))
        # ID increments by 1 with each loop iteration.
        id += 1
        
    # Here, normalization can be directly specified, achieving the same effect as `t = t / np.linalg.norm(t) `.
    db.bulk_add_items(vectors, normalize=True)

print(f"\n* [Insert data] Time cost {timer.last_timestamp_diff():>.4f} s.")
timer.middle_point()

res = db.query(db.head(10)[0], k=10)
print("  - Query vector: ", db.head(10)[0])
print("  - Database index of top 10 results: ", res[0])
print("  - Cosine similarity of top 10 results: ", res[1])
print(f"\n* [Query data] Time cost {timer.last_timestamp_diff():>.4f} s.")


timer.end()

# This sentence is for demo demonstration purposes, to clear the currently created .mvdb files from the database, but this is optional in actual use.
db.delete()
```


*Demo 2* -- **Bulk add vectors**


    
    * [Insert data] Time cost 1.0924 s.
      - Query vector:  [0.02898663 0.05306277 0.04289231 ... 0.0143056  0.01658325 0.04808333]
      - Database index of top 10 results:  [    0 67927 53447 47665 64134 13859 41949  5788 38082 18507]
      - Cosine similarity of top 10 results:  [1.         0.78101647 0.7777599  0.77717626 0.7759101  0.77581763
     0.77578723 0.77570754 0.77500904 0.7742009 ]
    
    * [Query data] Time cost 0.2244 s.


### Use field to improve Searching Recall


```python
try:
    from IPython.display import display_markdown
except ImportError:
    def display_markdown(text, raw=True):
        print(text)

import numpy as np

from spinesUtils.utils import Timer
from min_vec import MinVectorDB

timer = Timer()

# ===================================================================
# ========================= DEMO 3 ==================================
# ===================================================================
# Demo 3 -- Use field to improve Searching Recall
display_markdown("*Demo 3* -- **Use field to improve Searching Recall**", raw=True)

timer.start()

db = MinVectorDB(dim=1024, database_path='test_min_vec.mvdb', chunk_size=10000)

np.random.seed(23)


def get_test_vectors(shape):
    for i in range(shape[0]):
        yield np.random.random(shape[1])

with db.insert_session():     
    # Define the initial ID.
    id = 0
    vectors = []
    for t in get_test_vectors((100000, 1024)):
        # Vectors need to be normalized before writing to the database.
        # t = t / np.linalg.norm(t) 
        vectors.append((t, id, 'test_'+str(id // 100)))
        # ID increments by 1 with each loop iteration.
        id += 1
        
    db.bulk_add_items(vectors, normalize=True)

print(f"\n* [Insert data] Time cost {timer.last_timestamp_diff():>.4f} s.")
timer.middle_point()

res = db.query(db.head(10)[0], k=10, field=['test_0', 'test_3'])
print("  - Query vector: ", db.head(10)[0])
print("  - Database index of top 10 results: ", res[0])
print("  - Cosine similarity of top 10 results: ", res[1])
print(f"\n* [Query data] Time cost {timer.last_timestamp_diff():>.4f} s.")

timer.end()

# This sentence is for demo demonstration purposes, to clear the currently created .mvdb files from the database, but this is optional in actual use.
db.delete()
```


*Demo 3* -- **Use field to improve Searching Recall**


    
    * [Insert data] Time cost 1.0831 s.
      - Query vector:  [0.02898663 0.05306277 0.04289231 ... 0.0143056  0.01658325 0.04808333]
      - Database index of top 10 results:  [  0 396   9 359  98 317  20  66 347 337]
      - Cosine similarity of top 10 results:  [1.         0.7712989  0.76116776 0.7611464  0.7591922  0.7587052
     0.7574989  0.7574572  0.7573151  0.75730586]
    
    * [Query data] Time cost 0.1830 s.


### Use subset_indices to narrow down the search range


```python
try:
    from IPython.display import display_markdown
except ImportError:
    def display_markdown(text, raw=True):
        print(text)

import numpy as np

from spinesUtils.utils import Timer
from min_vec import MinVectorDB

timer = Timer()

# ===================================================================
# ========================= DEMO 4 ==================================
# ===================================================================
# Demo 4 -- Use subset_indices to narrow down the search range
display_markdown("*Demo 4* -- **Use subset_indices to narrow down the search range**", raw=True)

timer.start()

db = MinVectorDB(dim=1024, database_path='test_min_vec.mvdb', chunk_size=10000)

np.random.seed(23)


def get_test_vectors(shape):
    for i in range(shape[0]):
        yield np.random.random(shape[1])

with db.insert_session():     
    # Define the initial ID.
    id = 0
    vectors = []
    for t in get_test_vectors((100000, 1024)):
        # Vectors need to be normalized before writing to the database.
        # t = t / np.linalg.norm(t) 
        vectors.append((t, id, 'test_'+str(id // 100)))
        # ID increments by 1 with each loop iteration.
        id += 1
        
    db.bulk_add_items(vectors, normalize=True)

print(f"\n* [Insert data] Time cost {timer.last_timestamp_diff():>.4f} s.")
timer.middle_point()

res = db.query(db.head(10)[0], k=10, field=['test_0', 'test_3'], subset_indices=list(range(1000)))
print("  - Query vector: ", db.head(10)[0])
print("  - Database index of top 10 results: ", res[0])
print("  - Cosine similarity of top 10 results: ", res[1])
print(f"\n* [Query data] Time cost {timer.last_timestamp_diff():>.4f} s.")

timer.end()

# This sentence is for demo demonstration purposes, to clear the currently created .mvdb files from the database, but this is optional in actual use.
db.delete()
```


*Demo 4* -- **Use subset_indices to narrow down the search range**


    
    * [Insert data] Time cost 1.1138 s.
      - Query vector:  [0.02898663 0.05306277 0.04289231 ... 0.0143056  0.01658325 0.04808333]
      - Database index of top 10 results:  [  0 396   9 359  98 317  20  66 347 337]
      - Cosine similarity of top 10 results:  [1.         0.7712989  0.76116776 0.7611464  0.7591922  0.7587052
     0.7574989  0.7574572  0.7573151  0.75730586]
    
    * [Query data] Time cost 0.1830 s.

