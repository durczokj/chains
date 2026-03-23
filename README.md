# Chains

A Django application for tracking product code lifecycles. Events record when codes are introduced, discontinued, or chained (one code replaces another). A graph engine groups related codes into **product families** and **generations**.

## Data Model

```mermaid
erDiagram
    COUNTRY {
        string code PK
        string name
    }

    EVENT {
        int id PK
        string iso_country_code FK
        string comment
    }

    CODE_TYPE {
        string id PK
        string type
    }


    CODE_TRANSITION {
        int id PK
        int event_id FK
        string code_type_id FK
        string type
        date date
    }

    GENERATION_LINK {
        int id PK
        int predecessor_id FK
        int successor_id FK
        int source_transition_id FK
    }

    INTRODUCTION {
        int id PK
        int code_transition_id FK
        bigint introduction_code
    }

    DISCONTINUATION {
        int id PK
        int code_transition_id FK
        bigint discontinuation_code
    }

    CHAIN {
        int id PK
        int code_transition_id FK
        bigint introduction_code
        bigint discontinuation_code
    }


    PRODUCT_FAMILY {
        int id PK
        string code_type_id FK
        string identifier
        string iso_country_code FK
    }

    GENERATION {
        int id PK
        int product_family_id FK
        int introduction_id FK
        int discontinuation_id FK
    }

    COUNTRY ||--o{ EVENT : "has"
    COUNTRY ||--o{ PRODUCT_FAMILY : "has"
    EVENT ||--o{ CODE_TRANSITION : "has"
    CODE_TYPE ||--o{ CODE_TRANSITION : "has"
    CODE_TRANSITION ||--o| INTRODUCTION : "is"
    CODE_TRANSITION ||--o| DISCONTINUATION : "is"
    CODE_TRANSITION ||--o| CHAIN : "is"
    GENERATION ||--o{ GENERATION_LINK : "predecessor"
    GENERATION ||--o{ GENERATION_LINK : "successor"
    CODE_TRANSITION ||--o{ GENERATION_LINK : "source"
    CODE_TYPE ||--o{ PRODUCT_FAMILY : "has"
    PRODUCT_FAMILY ||--o{ GENERATION : "has"
    CODE_TRANSITION ||--o{ GENERATION : "introduction"
    CODE_TRANSITION ||--o{ GENERATION : "discontinuation"
```
