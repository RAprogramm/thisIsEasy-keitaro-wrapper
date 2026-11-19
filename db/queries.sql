-- Queries issued by the application through SQLAlchemy (parameter values inlined).

-- GET /api/campaigns: list campaigns created through the service.
SELECT id, keitaro_id, name, geo, created_at FROM campaigns ORDER BY id DESC LIMIT 100;

-- POST /api/campaigns: store a newly created campaign.
INSERT INTO campaigns (keitaro_id, name, geo, offer_id, domain_id, group_id, source_id)
VALUES (214971, 'test_rozanov_demo', 'DE', 18813, 1813, 9799, 836);

-- editor._log: find the local record for a Keitaro campaign id.
SELECT id, keitaro_id, name, geo, offer_id, domain_id, group_id, source_id, created_at
FROM campaigns
WHERE keitaro_id = 214971;

-- editor._log: append an offer change to the journal.
INSERT INTO offer_changes (campaign_id, offer_id, action)
VALUES (1, 18813, 'add');
