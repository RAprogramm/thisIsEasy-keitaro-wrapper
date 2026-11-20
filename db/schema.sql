CREATE TABLE campaigns (
    id SERIAL PRIMARY KEY,
    keitaro_id INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    geo VARCHAR(2) NOT NULL,
    offer_id INTEGER NOT NULL,
    domain_id INTEGER,
    group_id INTEGER,
    source_id INTEGER,
    idempotency_key VARCHAR(64) UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX ix_campaigns_keitaro_id ON campaigns (keitaro_id);

CREATE UNIQUE INDEX ix_campaigns_idempotency_key ON campaigns (idempotency_key);

CREATE TABLE offer_changes (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns (id) ON DELETE CASCADE,
    offer_id INTEGER NOT NULL,
    action VARCHAR(16) NOT NULL CHECK (action IN ('add', 'remove')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_offer_changes_campaign_id ON offer_changes (campaign_id);


CREATE TABLE stream_offers (
    id SERIAL PRIMARY KEY,
    keitaro_campaign_id INTEGER NOT NULL,
    stream_id INTEGER NOT NULL,
    offer_id INTEGER NOT NULL,
    share INTEGER NOT NULL DEFAULT 0,
    pinned BOOLEAN NOT NULL DEFAULT FALSE,
    published_share INTEGER NOT NULL DEFAULT 0,
    published_pinned BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(16) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'pending_add', 'pending_remove', 'removed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_stream_offers_campaign_stream_offer
        UNIQUE (keitaro_campaign_id, stream_id, offer_id)
);

CREATE INDEX ix_stream_offers_keitaro_campaign_id ON stream_offers (keitaro_campaign_id);
CREATE INDEX ix_stream_offers_stream_id ON stream_offers (stream_id);
CREATE INDEX ix_stream_offers_campaign_stream ON stream_offers (keitaro_campaign_id, stream_id);
