-- Disputes whose outcome does not join to a coherent §2.5 evidence
-- assessment. Phase 3 Group D derives every dispute's evidence tier as
-- the weakest link across real fulfillment factors and conditions the
-- outcome on that tier; a violating row means the causal chain broke
-- (a regression to the pre-causal pattern, where evidence quality was
-- a random label and outcomes were a flat draw).
--
-- Two violation classes, mirroring the generator
-- (generation/seed_retailer.py assemble_evidence /
-- generation/seed_distributor.py assemble_evidence):
--
--   missing assessment — the dispute does not join to the fulfillment
--     rows the assessment is assembled from (deduction -> order ->
--     shipment [-> pack record, POD evidence row retailer-side]), or
--     its filing date precedes the deduction.
--   tier exceeds a derivable factor — the stored evidence_quality is
--     STRONGER than a factor visible in the warehouse allows. Under
--     the weakest-link rule the tier can never exceed any factor:
--     ASN not sent / POD missing => weak; ASN late, POD partial,
--     manual-count pack, filing 31-60 days => moderate at best;
--     filing > 60 days => weak. The product-data factor is seed-side
--     (defect-profile score) and can only LOWER a tier, so it cannot
--     create a violation here — tiers below the visible-factor minimum
--     are expected, tiers above it are impossible.
--
-- Tier ranks: strong=0, moderate=1, weak=2. Violation: stored rank <
-- a derivable factor's rank.

with tier_rank as (
    select * from (values
        ('strong', 0), ('moderate', 1), ('weak', 2)
    ) as t (tier, rank)
),

retailer as (
    select
        disp.dispute_id,
        'retailer' as channel,
        disp.evidence_quality,
        tr.rank as stored_rank,
        ded.deduction_id,
        s.shipment_id,
        s.asn_sent,
        s.asn_sent_late,
        pr.pack_verification,
        pod.was_submitted as pod_submitted,
        pod.notes as pod_notes,
        (disp.filed_date - ded.deduction_date) as filing_delay_days
    from {{ ref('stg_retailer_disputes') }} disp
    left join tier_rank tr on tr.tier = disp.evidence_quality
    left join {{ ref('stg_retailer_deductions') }} ded
        on ded.deduction_id = disp.deduction_id
    left join {{ ref('stg_retailer_shipments') }} s
        on s.order_id = ded.order_id
    left join {{ ref('stg_retailer_pack_records') }} pr
        on pr.order_id = ded.order_id
    left join {{ ref('stg_retailer_dispute_evidence') }} pod
        on pod.dispute_id = disp.dispute_id
       and pod.evidence_type = 'POD'
),

retailer_violations as (
    select dispute_id, channel, evidence_quality,
        case
            when deduction_id is null or shipment_id is null
                 or pack_verification is null or pod_submitted is null
                then 'missing assessment join'
            when filing_delay_days is null or filing_delay_days < 1
                then 'filing date precedes deduction'
            when not asn_sent and stored_rank < 2
                then 'tier exceeds ASN factor (not sent => weak)'
            when asn_sent_late and stored_rank < 1
                then 'tier exceeds ASN factor (sent late => moderate at best)'
            when not pod_submitted and stored_rank < 2
                then 'tier exceeds POD factor (missing => weak)'
            when pod_notes = 'partial' and stored_rank < 1
                then 'tier exceeds POD factor (partial => moderate at best)'
            when pack_verification = 'manual_count' and stored_rank < 1
                then 'tier exceeds pack factor (manual count => moderate at best)'
            when filing_delay_days > 60 and stored_rank < 2
                then 'tier exceeds filing factor (>60d => weak)'
            when filing_delay_days > 30 and stored_rank < 1
                then 'tier exceeds filing factor (31-60d => moderate at best)'
        end as violation
    from retailer
),

distributor as (
    select
        disp.dispute_id,
        'distributor' as channel,
        disp.evidence_quality,
        tr.rank as stored_rank,
        ded.deduction_id,
        s.shipment_id,
        s.delivery_date,
        (disp.filed_date - ded.deduction_date) as filing_delay_days
    from {{ ref('stg_distributor_disputes') }} disp
    left join tier_rank tr on tr.tier = disp.evidence_quality
    left join {{ ref('stg_distributor_deductions') }} ded
        on ded.deduction_id = disp.deduction_id
    left join {{ ref('stg_distributor_shipments') }} s
        on s.order_id = ded.order_id
),

distributor_violations as (
    select dispute_id, channel, evidence_quality,
        case
            when deduction_id is null or shipment_id is null
                then 'missing assessment join'
            when filing_delay_days is null or filing_delay_days < 1
                then 'filing date precedes deduction'
            when delivery_date is null and stored_rank < 2
                then 'tier exceeds POD factor (no delivery => weak)'
            when filing_delay_days > 60 and stored_rank < 2
                then 'tier exceeds filing factor (>60d => weak)'
            when filing_delay_days > 30 and stored_rank < 1
                then 'tier exceeds filing factor (31-60d => moderate at best)'
        end as violation
    from distributor
)

select * from retailer_violations where violation is not null
union all
select * from distributor_violations where violation is not null
