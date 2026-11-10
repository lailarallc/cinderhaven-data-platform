-- reads truth through dbt's source and lands in public_marts under an innocuous name
select count(*) as n from {{ source('truth', 'injection_ledger') }}
