CREATE TABLE campaigns (
    id SERIAL PRIMARY KEY,
    keitaro_id INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    geo VARCHAR(2) NOT NULL,
    offer_id INTEGER NOT NULL,
    domain_id INTEGER,
    group_id INTEGER,
    source_id INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX ix_campaigns_keitaro_id ON campaigns (keitaro_id);

CREATE TABLE offer_changes (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns (id),
    offer_id INTEGER NOT NULL,
    action VARCHAR(16) NOT NULL CHECK (action IN ('add', 'remove')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_offer_changes_campaign_id ON offer_changes (campaign_id);
