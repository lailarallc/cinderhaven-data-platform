select * from {{ source('truth', 'injection_ledger') }}
