# Neo4j Graph Schema — `3eab12e0`

This schema describes **8 node label(s)** and **13 relationship type(s)**.

## Node Labels

### (:Article)

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_id` | Integer | 13817, 13818, 13838 |
| `author` | String | "J Vignesh", "Ian Walker", "ABMN Staff" |
| `date` | DateTime | 2019-02-18T00:00:00.000000000+00:00, 2017-11-24T04:47:00.000000000+00:00, 2023-06-13T09:38:00.000000000+00:00 |
| `id` | String | "ART49144589301", "ART17463145723", "ART82973354614" |
| `sentiment` | Float | 0.298, 0.238, 0.316 |
| `siteName` | String | "SBWire", "The Economic Times", "MarketWatch" |
| `summary` | String | "Free Sample Report + All Related Graphs & Charts @ : http...", "BENGALURU: Does your Facebook profile declare you have a ...", "Capita said Tuesday that it has been awarded a five-year ..." |
| `title` | String | "Recommendation Engine Market to Witness Huge Growth by 20...", "Data analytics makes a blockbuster debut in Bollywood", "Capita Gets Initial 5-Year, GBP50 Mln Contract With City ..." |

### (:Chunk)

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_id` | Integer | 129245, 129246, 129256 |
| `embed_dim` | Integer | 512 |
| `embed_model_name` | String | "jinaai/jina-embeddings-v5-text-nano" |
| `embedding` | List | [-0.06396484375, -0.07025146484375, -0.007755279541015625], [-0.038909912109375, -0.10223388671875, -0.02520751953125], [-0.0222320556640625, -0.017242431640625, 0.0552978515625] |
| `id` | String | "0043677bdfffe017c2ed4fe30ed997f6b921ef9c", "64888aeeec8fad31309b40237aad92a82d33e384", "9141d5d3ff8d775a0ffea605fb300ef047bbd0a4" |
| `text` | String | "Free Sample Report + All Related Graphs & Charts @ : http...", "TYPE 2 3.2 Recommendation Engine Market Size by Type 3.3 ...", "Outsourcing giant Capita – currently facing possible regu..." |

### (:City)

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_id` | Integer | 13804, 13807, 13809 |
| `id` | String | "EZHWv2xKgN92oYDKSjhJ2gw", "E_FZVnahVPq64PwoufmS6oA", "ENFWeK7YSOSyL8SWvT14yEw" |
| `name` | String | "Seattle", "Rome", "Manchester" |
| `summary` | String | "City in and county seat of King County, Washington, Unite...", "Capital and largest city of Italy", "Major city in Greater Manchester, England, UK" |

### (:Country)

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_id` | Integer | 13802, 13805, 13808 |
| `id` | String | "E01d4EK33MmCosgI2KXa4-A", "Es0LZKHtaPf2VSixCSIlcEg", "EnI6g1AI9NcC6yCohEYEb2A" |
| `name` | String | "United States of America", "Italy", "United Kingdom" |
| `summary` | String | "Country in North America", "Country in Southern Europe", "Country in north-west Europe" |

### (:Fewshot)

| Property | Type | Example Values |
| --- | --- | --- |
| `Cypher` | String | "MATCH (p1:Person {{name:"Emil Eifrem"}}), (p2:Person {{na...", "MATCH (o:Organization {{name:"Google"}})<-[:MENTIONS]-(a:...", "CALL apoc.ml.openai.embedding(["Are there any news regard..." |
| `Question` | String | "How is Emil Eifrem connected to Michael Hunger?", "What are the latest news regarding Google?", "Are there any news regarding return to office policies?" |
| `_src_id` | Integer | 237352, 237353, 237354 |
| `id` | Integer | 2, 3, 4 |

### (:IndustryCategory)

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_id` | Integer | 660, 661, 662 |
| `id` | String | "EUNd__O4zMNW81lAXNK2GNw", "Efc_gAH4HM_SKwiKysIzA1w", "EqFeVtLRWOUqTdzVhcYwBBQ" |
| `name` | String | "Electronic Products Manufacturers", "Enterprise Software Companies", "Computer Hardware Companies" |

### (:Organization)

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_id` | Integer | 0, 1, 2 |
| `diffbotId` | String | "https://diffbot.com/entity/E0ZU8eCc5OaqS1LU9qE3n3w", "https://diffbot.com/entity/E91iaB3VQN3K-0YIMTmJjRw", "https://diffbot.com/entity/Ep4YdYe6nPdaQnvOFxKB_qQ" |
| `id` | String | "E0ZU8eCc5OaqS1LU9qE3n3w", "E91iaB3VQN3K-0YIMTmJjRw", "Ep4YdYe6nPdaQnvOFxKB_qQ" |
| `isDissolved` | Boolean | False, True |
| `isPublic` | Boolean | False, True |
| `motto` | String | "", "Securing the most prolific technologies in the world | Ac...", "Supply Chain Management & Advanced Data Analytics." |
| `name` | String | "New Energy Group", "Deja vu Security", "Clarity Insights" |
| `nbrEmployees` | Integer | 375, 30, 175 |
| `revenue` | Float | 120000000.0, 4600000.0, 59000000.0 |
| `summary` | String | "Software company based in Rome, Metropolitan City of Rome...", "Software company based in Seattle, Washington, United Sta...", "Software company based in Chicago, Illinois, United States" |

### (:Person)

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_id` | Integer | 584, 585, 586 |
| `id` | String | "Eaf0bpz6NNoqLVUCqNZPAew", "EiBXh7ntpMfOdhqFJDmDw4A", "EPXfNzMUGMfygOTJrdzjq-g" |
| `name` | String | "Julie Spellman Sweet", "Arun Sarin", "Gilles Pélisson" |
| `summary` | String | "CEO at Accenture", "American businessman", "French businessman" |

## Relationship Types

### [:HAS_BOARD_MEMBER]

**Connections:**

- `(:Organization)-[:HAS_BOARD_MEMBER]->(:Person)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17295, 17569, 17568 |

### [:HAS_CATEGORY]

**Connections:**

- `(:Organization)-[:HAS_CATEGORY]->(:IndustryCategory)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17239, 17233, 17235 |

### [:HAS_CEO]

**Connections:**

- `(:Organization)-[:HAS_CEO]->(:Person)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17325, 17378, 17421 |

### [:HAS_CHILD]

**Connections:**

- `(:Person)-[:HAS_CHILD]->(:Person)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17123, 17124, 17125 |

### [:HAS_CHUNK]

**Connections:**

- `(:Article)-[:HAS_CHUNK]->(:Chunk)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 281877, 281878, 281892 |

### [:HAS_COMPETITOR]

**Connections:**

- `(:Organization)-[:HAS_COMPETITOR]->(:Organization)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17531, 17977, 17975 |

### [:HAS_INVESTOR]

**Connections:**

- `(:Organization)-[:HAS_INVESTOR]->(:Organization)`
- `(:Organization)-[:HAS_INVESTOR]->(:Person)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17985, 18281, 18282 |

### [:HAS_PARENT]

**Connections:**

- `(:Person)-[:HAS_PARENT]->(:Person)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17119, 17120, 17121 |

### [:HAS_SUBSIDIARY]

**Connections:**

- `(:Organization)-[:HAS_SUBSIDIARY]->(:Organization)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17294, 17330, 17435 |

### [:HAS_SUPPLIER]

**Connections:**

- `(:Organization)-[:HAS_SUPPLIER]->(:Organization)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17263, 17287, 17331 |

### [:IN_CITY]

**Connections:**

- `(:Organization)-[:IN_CITY]->(:City)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 147018, 147024, 147073 |

### [:IN_COUNTRY]

**Connections:**

- `(:City)-[:IN_COUNTRY]->(:Country)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17389, 30415, 21692 |

### [:MENTIONS]

**Connections:**

- `(:Article)-[:MENTIONS]->(:Organization)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17245, 17247, 17248 |
