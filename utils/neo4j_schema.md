# Neo4j Graph Schema — `companies`

This schema describes **10 node label(s)** and **14 relationship type(s)**.

## Node Labels

### (:Article)

| Property | Type | Example Values |
| --- | --- | --- |
| `author` | String | "David Correa", "Meha Agarwal", "Tyler Cowen" |
| `date` | DateTime | 2022-03-10T00:00:00.000000000+00:00, 2021-12-03T13:14:00.000000000+00:00, 2020-08-03T00:00:00.000000000+00:00 |
| `id` | String | "ART176872705964", "ART207354016827", "ART266798609405" |
| `sentiment` | Float | 0.856, 0.908, 0.866 |
| `siteName` | String | "MrWeb", "EIN Presswire", "Inc42 Media" |
| `summary` | String | "Boston and Mumbai-based consumer behavior analyses platfo...", "Market is driven by factors such as perpetually growing i...", "Pitney Bowes, a global technology company has selected si..." |
| `title` | String | "Funds for Consumer Behavior Specialist Infinite Analytics", "AI in Retail Market is Expected to Witness a Sustainable ...", "Pitney Bowes Global Accelerator Programme Names Six India..." |

### (:Chunk)

| Property | Type | Example Values |
| --- | --- | --- |
| `embedding` | List | [0.008298696018755436, -0.013650904409587383, -0.0034144592937082052], [0.00786040909588337, -0.0271877683699131, -0.002703254111111164], [-0.00862328615039587, -0.0043186768889427185, 0.004913022741675377] |
| `embedding_google` | List | [-0.019655367359519005, -0.037632301449775696, -0.013469232246279716], [-0.011500051245093346, -0.034330546855926514, 0.018356792628765106], [0.001895332708954811, -0.03579990938305855, -0.01455572247505188] |
| `embedding_google_004` | List | [0.03132466971874237, -0.00970673281699419, -0.08683867752552032], [-0.0031520589254796505, -0.015331501141190529, -0.010702344588935375], [0.05774576961994171, -0.014640887267887592, -0.03053850494325161] |
| `embedding_sbert` | List | [-0.05072962865233421, -0.09769032895565033, -0.08340393751859665], [-0.02165641263127327, -0.037082038819789886, 0.01983681507408619], [-0.034024689346551895, -0.04924176260828972, -0.11681362986564636] |
| `id` | String | "b49cf751fd972c47fa0a4932d3e9624e6e15c21d", "34dc09d4ec77470c6a2d345e64a6e8a0420df81c", "6cd26aae0c7c850083c12dc6b6c5c566dcbc194b" |
| `text` | String | "Boston and Mumbai-based consumer behavior analyses platfo...", "Market is driven by factors such as perpetually growing i...", "Pitney Bowes, a global technology company has selected si..." |

### (:City)

| Property | Type | Example Values |
| --- | --- | --- |
| `id` | String | "EZHWv2xKgN92oYDKSjhJ2gw", "E_FZVnahVPq64PwoufmS6oA", "ENFWeK7YSOSyL8SWvT14yEw" |
| `name` | String | "Seattle", "Rome", "Manchester" |
| `summary` | String | "City in and county seat of King County, Washington, Unite...", "Capital and largest city of Italy", "Major city in Greater Manchester, England, UK" |

### (:Country)

| Property | Type | Example Values |
| --- | --- | --- |
| `id` | String | "E01d4EK33MmCosgI2KXa4-A", "Es0LZKHtaPf2VSixCSIlcEg", "EnI6g1AI9NcC6yCohEYEb2A" |
| `name` | String | "United States of America", "Italy", "United Kingdom" |
| `summary` | String | "Country in North America", "Country in Southern Europe", "Country in north-west Europe" |

### (:Fewshot)

| Property | Type | Example Values |
| --- | --- | --- |
| `Cypher` | String | "MATCH (p1:Person {{name:"Emil Eifrem"}}), (p2:Person {{na...", "MATCH (o:Organization {{name:"Google"}})<-[:MENTIONS]-(a:...", "CALL apoc.ml.openai.embedding(["Are there any news regard..." |
| `Question` | String | "How is Emil Eifrem connected to Michael Hunger?", "What are the latest news regarding Google?", "Are there any news regarding return to office policies?" |
| `embedding` | List | [-0.013787841, -0.03527378, -0.0077805766], [-0.004729776, 0.007460863, 0.012717691], [-0.0051900465, -0.023930592, 0.004344384] |
| `id` | Integer | 2, 3, 4 |

### (:IndustryCategory)

| Property | Type | Example Values |
| --- | --- | --- |
| `id` | String | "EUNd__O4zMNW81lAXNK2GNw", "Efc_gAH4HM_SKwiKysIzA1w", "EqFeVtLRWOUqTdzVhcYwBBQ" |
| `name` | String | "Electronic Products Manufacturers", "Enterprise Software Companies", "Computer Hardware Companies" |

### (:Organization)

| Property | Type | Example Values |
| --- | --- | --- |
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
| `id` | String | "Eaf0bpz6NNoqLVUCqNZPAew", "EiBXh7ntpMfOdhqFJDmDw4A", "EPXfNzMUGMfygOTJrdzjq-g" |
| `name` | String | "Julie Spellman Sweet", "Arun Sarin", "Gilles Pélisson" |
| `summary` | String | "CEO at Accenture", "American businessman", "French businessman" |

### (:_Bloom_Perspective_)

| Property | Type | Example Values |
| --- | --- | --- |
| `data` | String | "{"name":"Companies","id":"3c5153c0-d737-11ee-afd5-7529892..." |
| `id` | String | "3c5153c0-d737-11ee-afd5-7529892ea4a1" |
| `name` | String | "Companies" |
| `roles` | List | ["companies", "admin"] |
| `version` | String | "2.12.0" |

### (:_Bloom_Scene_)

| Property | Type | Example Values |
| --- | --- | --- |
| `createdAt` | Integer | 1709234285101 |
| `createdBy` | String | "neo4j" |
| `gds` | String | "{"gdsRules":[],"gdsResults":{}}" |
| `id` | String | "4384bdd0-d737-11ee-afd5-7529892ea4a1" |
| `lastModified` | Integer | 1709234288192 |
| `name` | String | "Untitled Scene" |
| `nodes` | String | "[]" |
| `numOfNodes` | Integer | 0 |
| `numOfRels` | Integer | 0 |
| `ranges` | String | "[]" |
| `relationships` | String | "[]" |
| `roles` | List | [] |
| `style` | String | "{"type":"scene","id":"4384bdd0-d737-11ee-afd5-7529892ea4a..." |
| `version` | String | "2.12.0" |
| `visualisation` | String | "{"layoutDirection":"forceDirected","layoutType":"forceDir..." |

## Relationship Types

### [:HAS_BOARD_MEMBER]

**Connections:**

- `(:Organization)-[:HAS_BOARD_MEMBER]->(:Person)`

_No properties._

### [:HAS_CATEGORY]

**Connections:**

- `(:Organization)-[:HAS_CATEGORY]->(:IndustryCategory)`

_No properties._

### [:HAS_CEO]

**Connections:**

- `(:Organization)-[:HAS_CEO]->(:Person)`

_No properties._

### [:HAS_CHILD]

**Connections:**

- `(:Person)-[:HAS_CHILD]->(:Person)`

_No properties._

### [:HAS_CHUNK]

**Connections:**

- `(:Article)-[:HAS_CHUNK]->(:Chunk)`

_No properties._

### [:HAS_COMPETITOR]

**Connections:**

- `(:Organization)-[:HAS_COMPETITOR]->(:Organization)`

_No properties._

### [:HAS_INVESTOR]

**Connections:**

- `(:Organization)-[:HAS_INVESTOR]->(:Organization)`
- `(:Organization)-[:HAS_INVESTOR]->(:Person)`

_No properties._

### [:HAS_PARENT]

**Connections:**

- `(:Person)-[:HAS_PARENT]->(:Person)`

_No properties._

### [:HAS_SUBSIDIARY]

**Connections:**

- `(:Organization)-[:HAS_SUBSIDIARY]->(:Organization)`

_No properties._

### [:HAS_SUPPLIER]

**Connections:**

- `(:Organization)-[:HAS_SUPPLIER]->(:Organization)`

_No properties._

### [:IN_CITY]

**Connections:**

- `(:Organization)-[:IN_CITY]->(:City)`

_No properties._

### [:IN_COUNTRY]

**Connections:**

- `(:City)-[:IN_COUNTRY]->(:Country)`

_No properties._

### [:MENTIONS]

**Connections:**

- `(:Article)-[:MENTIONS]->(:Organization)`

_No properties._

### [:_Bloom_HAS_SCENE_]

**Connections:**

- `(:_Bloom_Perspective_)-[:_Bloom_HAS_SCENE_]->(:_Bloom_Scene_)`

_No properties._
