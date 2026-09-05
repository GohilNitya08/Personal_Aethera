-- Upgrade existing AETHERA databases for workspace visibility and access requests.
-- Run once against MySQL before deploying the corresponding application code.

ALTER TABLE workspaces
    MODIFY visibility ENUM('PRIVATE', 'SHARED', 'PUBLIC') DEFAULT 'PRIVATE';

CREATE TABLE IF NOT EXISTS workspace_join_requests (
    request_id VARCHAR(36) PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    status ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (workspace_id)
        REFERENCES workspaces(workspace_id)
        ON DELETE CASCADE,
    FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,
    UNIQUE (workspace_id, user_id)
);
