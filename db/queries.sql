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

-- editor sync: tracked offers for a stream.
SELECT id, keitaro_campaign_id, stream_id, offer_id, share, pinned, published_share, published_pinned, status, created_at
FROM stream_offers
WHERE keitaro_campaign_id = 1000 AND stream_id = 2;

-- editor add: insert a pending offer.
INSERT INTO stream_offers (keitaro_campaign_id, stream_id, offer_id, share, pinned, status)
VALUES (1000, 2, 200, 0, FALSE, 'pending_add');

-- editor push: mark staged offers as published.
UPDATE stream_offers
SET status = 'active', published_share = share, published_pinned = pinned
WHERE keitaro_campaign_id = 1000 AND stream_id = 2 AND status = 'pending_add';

-- editor._log: append an offer change to the journal.
INSERT INTO offer_changes (campaign_id, offer_id, action)
VALUES (1, 18813, 'add');

-- ORM cascade on CampaignRecord deletion (session.delete(record)): the journal
-- rows are dropped first, then the campaign itself.
DELETE FROM offer_changes WHERE campaign_id = 1;
DELETE FROM campaigns WHERE id = 1;
