# Neo4j Graph Schema — `3eab12e0`

This schema describes **8 node label(s)** and **13 relationship type(s)**.

## Node Labels

### (:Article)

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_id` | Integer | 13817, 13829, 13831 |
| `author` | String | "Alex Scroxton", "Paul Kunert", "Finextra" |
| `date` | DateTime | 2019-02-18T00:00:00.000000000+00:00, 2023-06-14T17:30:00.000000000+00:00, 2023-06-14T13:34:12.000000000+00:00 |
| `id` | String | "ART49144589301", "ART11678562965", "ART152671705860" |
| `sentiment` | Float | nan, 0.518, -0.205 |
| `siteName` | String | "SBWire", "ComputerWeekly.com", "theregister.com" |
| `summary` | String | "Free Sample Report + All Related Graphs & Charts @ : http...", "Outsourcing giant Capita – currently facing possible regu...", "Capita, which is still dealing with a digital break-in th..." |
| `title` | String | "Recommendation Engine Market to Witness Huge Growth by 20...", "Ransomware-stricken Capita to run Action Fraud successor", "Capita wins £50M fraud reporting contract with City of Lo..." |

### (:Chunk)

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_id` | Integer | 129245, 129246, 129315 |
| `id` | String | "0043677bdfffe017c2ed4fe30ed997f6b921ef9c", "64888aeeec8fad31309b40237aad92a82d33e384", "d25b70e5de23a5a7594222ffc1de2b6950477046" |
| `text` | String | "Free Sample Report + All Related Graphs & Charts @ : http...", "TYPE 2 3.2 Recommendation Engine Market Size by Type 3.3 ...", "Accenture is continuing on its buying spree, this time ac..." |

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

### (:IndustryCategory)

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_id` | Integer | 660, 661, 662 |
| `id` | String | "EUNd__O4zMNW81lAXNK2GNw", "Efc_gAH4HM_SKwiKysIzA1w", "EqFeVtLRWOUqTdzVhcYwBBQ" |
| `name` | String | "Electronic Products Manufacturers", "Enterprise Software Companies", "Computer Hardware Companies" |

### (:Migrated)

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_id` | Integer | 2027, 2028, 0 |
| `diffbotId` | String | "https://diffbot.com/entity/Ef-uCgYJKNP2Ruo3Td92MFA", "https://diffbot.com/entity/EhNWgp6G2Nqy1bLeeZacyLw", "https://diffbot.com/entity/E0ZU8eCc5OaqS1LU9qE3n3w" |
| `id` | String | "Ef-uCgYJKNP2Ruo3Td92MFA", "EhNWgp6G2Nqy1bLeeZacyLw", "E0ZU8eCc5OaqS1LU9qE3n3w" |
| `isDissolved` | Boolean | False, True |
| `isPublic` | Boolean | False, True |
| `motto` | String | "", "Securing the most prolific technologies in the world | Ac...", "Supply Chain Management & Advanced Data Analytics." |
| `name` | String | "Telligent Systems", "Everbridge", "New Energy Group" |
| `nbrEmployees` | Integer | 375, 30, 175 |
| `revenue` | Float | 120000000.0, 4600000.0, 59000000.0 |
| `summary` | String | "Software company based in Dallas, Texas, United States", "American publicly traded enterprise software company", "Software company based in Rome, Metropolitan City of Rome..." |

### (:Organization)

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_id` | Integer | 2027, 2028, 0 |
| `diffbotId` | String | "https://diffbot.com/entity/Ef-uCgYJKNP2Ruo3Td92MFA", "https://diffbot.com/entity/EhNWgp6G2Nqy1bLeeZacyLw", "https://diffbot.com/entity/E0ZU8eCc5OaqS1LU9qE3n3w" |
| `id` | String | "Ef-uCgYJKNP2Ruo3Td92MFA", "EhNWgp6G2Nqy1bLeeZacyLw", "E0ZU8eCc5OaqS1LU9qE3n3w" |
| `isDissolved` | Boolean | False, True |
| `isPublic` | Boolean | False, True |
| `motto` | String | "", "Securing the most prolific technologies in the world | Ac...", "Supply Chain Management & Advanced Data Analytics." |
| `name` | String | "Telligent Systems", "Everbridge", "New Energy Group" |
| `nbrEmployees` | Integer | 375, 30, 175 |
| `revenue` | Float | 120000000.0, 4600000.0, 59000000.0 |
| `summary` | String | "Software company based in Dallas, Texas, United States", "American publicly traded enterprise software company", "Software company based in Rome, Metropolitan City of Rome..." |

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

- `(:Migrated)-[:HAS_BOARD_MEMBER]->(:Migrated)`
- `(:Migrated)-[:HAS_BOARD_MEMBER]->(:Person)`
- `(:Organization)-[:HAS_BOARD_MEMBER]->(:Migrated)`
- `(:Organization)-[:HAS_BOARD_MEMBER]->(:Person)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 80250, 80307, 80308 |

### [:HAS_CATEGORY]

**Connections:**

- `(:Migrated)-[:HAS_CATEGORY]->(:IndustryCategory)`
- `(:Migrated)-[:HAS_CATEGORY]->(:Migrated)`
- `(:Organization)-[:HAS_CATEGORY]->(:IndustryCategory)`
- `(:Organization)-[:HAS_CATEGORY]->(:Migrated)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 80236, 80237, 80238 |

### [:HAS_CEO]

**Connections:**

- `(:Migrated)-[:HAS_CEO]->(:Migrated)`
- `(:Migrated)-[:HAS_CEO]->(:Person)`
- `(:Organization)-[:HAS_CEO]->(:Migrated)`
- `(:Organization)-[:HAS_CEO]->(:Person)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 80254, 17325, 17378 |

### [:HAS_CHILD]

**Connections:**

- `(:Migrated)-[:HAS_CHILD]->(:Migrated)`
- `(:Migrated)-[:HAS_CHILD]->(:Person)`
- `(:Person)-[:HAS_CHILD]->(:Migrated)`
- `(:Person)-[:HAS_CHILD]->(:Person)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17129, 17130, 17150 |

### [:HAS_CHUNK]

**Connections:**

- `(:Article)-[:HAS_CHUNK]->(:Chunk)`
- `(:Article)-[:HAS_CHUNK]->(:Migrated)`
- `(:Migrated)-[:HAS_CHUNK]->(:Chunk)`
- `(:Migrated)-[:HAS_CHUNK]->(:Migrated)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 281877, 281878, 281950 |

### [:HAS_COMPETITOR]

**Connections:**

- `(:Migrated)-[:HAS_COMPETITOR]->(:Migrated)`
- `(:Migrated)-[:HAS_COMPETITOR]->(:Organization)`
- `(:Organization)-[:HAS_COMPETITOR]->(:Migrated)`
- `(:Organization)-[:HAS_COMPETITOR]->(:Organization)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 80318, 80313, 80310 |

### [:HAS_INVESTOR]

**Connections:**

- `(:Migrated)-[:HAS_INVESTOR]->(:Migrated)`
- `(:Migrated)-[:HAS_INVESTOR]->(:Organization)`
- `(:Migrated)-[:HAS_INVESTOR]->(:Person)`
- `(:Organization)-[:HAS_INVESTOR]->(:Migrated)`
- `(:Organization)-[:HAS_INVESTOR]->(:Organization)`
- `(:Organization)-[:HAS_INVESTOR]->(:Person)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17985, 18281, 18282 |

### [:HAS_PARENT]

**Connections:**

- `(:Migrated)-[:HAS_PARENT]->(:Migrated)`
- `(:Migrated)-[:HAS_PARENT]->(:Person)`
- `(:Person)-[:HAS_PARENT]->(:Migrated)`
- `(:Person)-[:HAS_PARENT]->(:Person)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17128, 17149, 17197 |

### [:HAS_SUBSIDIARY]

**Connections:**

- `(:Migrated)-[:HAS_SUBSIDIARY]->(:Migrated)`
- `(:Migrated)-[:HAS_SUBSIDIARY]->(:Organization)`
- `(:Organization)-[:HAS_SUBSIDIARY]->(:Migrated)`
- `(:Organization)-[:HAS_SUBSIDIARY]->(:Organization)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 80246, 80286, 80290 |

### [:HAS_SUPPLIER]

**Connections:**

- `(:Migrated)-[:HAS_SUPPLIER]->(:Migrated)`
- `(:Migrated)-[:HAS_SUPPLIER]->(:Organization)`
- `(:Organization)-[:HAS_SUPPLIER]->(:Migrated)`
- `(:Organization)-[:HAS_SUPPLIER]->(:Organization)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 80247, 80249, 80248 |

### [:IN_CITY]

**Connections:**

- `(:Migrated)-[:IN_CITY]->(:City)`
- `(:Migrated)-[:IN_CITY]->(:Migrated)`
- `(:Organization)-[:IN_CITY]->(:City)`
- `(:Organization)-[:IN_CITY]->(:Migrated)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 150095, 151456, 153395 |

### [:IN_COUNTRY]

**Connections:**

- `(:City)-[:IN_COUNTRY]->(:Country)`
- `(:City)-[:IN_COUNTRY]->(:Migrated)`
- `(:Migrated)-[:IN_COUNTRY]->(:Country)`
- `(:Migrated)-[:IN_COUNTRY]->(:Migrated)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17389, 30415, 21692 |

### [:MENTIONS]

**Connections:**

- `(:Article)-[:MENTIONS]->(:Migrated)`
- `(:Article)-[:MENTIONS]->(:Organization)`
- `(:Migrated)-[:MENTIONS]->(:Migrated)`
- `(:Migrated)-[:MENTIONS]->(:Organization)`

**Properties:**

| Property | Type | Example Values |
| --- | --- | --- |
| `_src_rid` | Integer | 17245, 17247, 17248 |
