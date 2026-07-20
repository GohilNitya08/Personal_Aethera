CREATE TABLE users (
    user_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    username VARCHAR(30) NOT NULL UNIQUE,
    full_name VARCHAR(100) NOT NULL,

    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255),

    google_id VARCHAR(255) UNIQUE,

    account_type ENUM(
        'PUBLIC',
        'STUDENT_PENDING',
        'STUDENT_VERIFIED',
        'EMPLOYEE_PENDING',
        'EMPLOYEE_VERIFIED',
        'ADMIN'
    ) DEFAULT 'PUBLIC',

    enrollment_id VARCHAR(30) UNIQUE,
    employee_id VARCHAR(30) UNIQUE,

    profile_picture TEXT,
    bio TEXT,

    storage_used BIGINT DEFAULT 0,
    storage_limit BIGINT DEFAULT 16106127360,

    email_verified BOOLEAN DEFAULT FALSE,
    two_factor_enabled BOOLEAN DEFAULT FALSE,

    account_status ENUM(
        'ACTIVE',
        'SUSPENDED',
        'DELETED'
    ) DEFAULT 'ACTIVE',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login TIMESTAMP NULL
);

CREATE TABLE workspaces (
    workspace_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    user_id BIGINT NOT NULL,

    workspace_name VARCHAR(100) NOT NULL,

    description TEXT,

    workspace_type ENUM('PERSONAL', 'INSTITUTION') NOT NULL,

    visibility ENUM('PRIVATE', 'SHARED') DEFAULT 'PRIVATE',

    storage_used BIGINT DEFAULT 0,

    storage_limit BIGINT DEFAULT 0,

    color VARCHAR(20) DEFAULT 'blue',

    is_archived BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE
);

