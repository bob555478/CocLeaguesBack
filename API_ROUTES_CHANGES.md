# API Routes Changelog (`API_ROUTES_CHANGES.md`)

This document describes all additions and changes made to [`API_ROUTES.md`](./API_ROUTES.md) to support:
1. Targeting the external backend at **`http://0.0.0.0:8000/`** (via [`src/services/backendClient.js`](./src/services/backendClient.js)) with automatic fallback to [`src/mocks/`](./src/mocks/index.js) when the backend is not responding.
2. **In-Game Player Search** during Registration and Account Management (`GET /api/coc/players`).
3. **Multi-Account In-Game Player & Clan Linking** (`user_ingame_accounts` table and `/api/accounts*` endpoints).
4. **Role-Based Schedule Access** (`Normal User / Member` read-only schedule view vs `Clan Admin / Leader` editable schedule view via `PATCH /api/accounts/:playerTag/role`).

---



## 2. New Database Table Added (`user_ingame_accounts`)

To support linking one online user (`user_id`) to one or more Clash of Clans in-game players (`player_tag`) and their assigned clan (`clan_tag`), the following table was added to the database schema:

```sql
CREATE TABLE IF NOT EXISTS user_ingame_accounts (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  player_tag TEXT NOT NULL,
  player_name TEXT NOT NULL,
  town_hall_level INTEGER NOT NULL DEFAULT 16,
  trophies INTEGER NOT NULL DEFAULT 0,
  role TEXT NOT NULL DEFAULT 'member',
  clan_tag TEXT NOT NULL,
  clan_name TEXT NOT NULL,
  clan_badge_url TEXT,
  is_active BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_ingame_accounts_user_id
  ON user_ingame_accounts (user_id);
```

---

## 3. New Routes Added to `API_ROUTES.md`

### A. Clash of Clans Player Search Route

#### `GET /api/coc/players`
- **Purpose**: Searches Clash of Clans in-game players by name or `#TAG` so users can link their online account to their in-game player(s) and automatically detect the player's current clan.
- **Query Parameters**:
  - `q` (optional `string`): Player name substring or player tag (e.g. `Artorius` or `#P902L8Q`).
  - `clanTag` (optional `string`): Filter results to a specific clan tag (e.g. `#2PP`).
- **Response (`200 OK`)**:
  ```json
  {
    "items": [
      {
        "tag": "#P902L8Q",
        "name": "Artorius",
        "townHallLevel": 17,
        "expLevel": 254,
        "trophies": 5890,
        "role": "leader",
        "clan": {
          "tag": "#2PP",
          "name": "The Order",
          "clanLevel": 28,
          "badgeUrls": {
            "small": "...",
            "medium": "..."
          }
        }
      }
    ],
    "source": "live"
  }
  ```

---

### B. User Linked In-Game Accounts Routes (`/api/accounts`)

#### 1. `GET /api/accounts`
- **Purpose**: Lists all Clash of Clans in-game player accounts linked to the authenticated online user (`ORDER BY is_active DESC, created_at ASC`).
- **Query Parameters / Headers**:
  - `Authorization: Bearer <neon_auth_jwt>` (or `?userId=<id>` fallback).
- **Response (`200 OK`)**:
  ```json
  {
    "items": [
      {
        "id": "user_123:#P902L8Q",
        "user_id": "user_123",
        "player_tag": "#P902L8Q",
        "player_name": "Artorius",
        "town_hall_level": 17,
        "trophies": 5890,
        "role": "leader",
        "clan_tag": "#2PP",
        "clan_name": "The Order",
        "clan_badge_url": "...",
        "is_active": true,
        "created_at": "2026-10-30T12:00:00.000Z",
        "updated_at": "2026-10-30T12:00:00.000Z"
      }
    ],
    "accounts": [ ... ]
  }
  ```

#### 2. `POST /api/accounts`
- **Purpose**: Links one or more in-game players and their assigned clan to the online user (used during Registration and in the "Manage Linked In-Game Accounts" modal). Automatically marks the first linked account as `is_active = true` if the user has no active account yet.
- **Request Body**:
  ```json
  {
    "userId": "user_123",
    "accounts": [
      {
        "playerTag": "#P902L8Q",
        "playerName": "Artorius",
        "townHallLevel": 17,
        "trophies": 5890,
        "role": "leader",
        "clanTag": "#2PP",
        "clanName": "The Order",
        "clanBadgeUrl": "...",
        "isActive": true
      }
    ]
  }
  ```
- **Response (`200 OK`)**: Returns `{ "items": [...], "accounts": [...] }` with the user's updated list of linked in-game accounts.

#### 3. `PATCH /api/accounts/:playerTag/activate`
- **Purpose**: Switches the user's currently active in-game player (`is_active = true` for `:playerTag`, `is_active = false` for all other accounts of that user). Switching the active player automatically switches the UI to that player's clan and weekly schedule.
- **Request Body**: `{ "userId": "user_123" }`
- **Response (`200 OK`)**: Returns `{ "items": [...], "accounts": [...] }`.

#### 4. `PATCH /api/accounts/:playerTag/clan`
- **Purpose**: Updates the clan (`clan_tag`, `clan_name`, `clan_badge_url`) assigned to a specific linked in-game player.
- **Request Body**:
  ```json
  {
    "userId": "user_123",
    "clanTag": "#2Q89J0L2",
    "clanName": "Apex Legends CoC",
    "clanBadgeUrl": "..."
  }
  ```
- **Response (`200 OK`)**: Returns `{ "items": [...], "accounts": [...] }`.

#### 5. `PATCH /api/accounts/:playerTag/role`
- **Purpose**: Updates the clan role (`"member"` vs `"leader"` / `"coLeader"` / `"admin"`) of a linked in-game player, determining whether the user views the CWL schedule in **Member (Read-Only)** mode or **Clan Admin (Editable)** mode.
- **Request Body**:
  ```json
  {
    "userId": "user_123",
    "role": "leader"
  }
  ```
- **Response (`200 OK`)**: Returns `{ "items": [...], "accounts": [...] }`.

#### 6. `DELETE /api/accounts/:playerTag`
- **Purpose**: Unlinks an in-game player from the user's profile.
- **Validation Rule**: Enforces that a user **must have at least 1 linked in-game player**. If the user only has `1` linked account left, returns `400 Bad Request` with `{ "error": "Cannot remove your last in-game account. Every user must have at least 1 linked in-game player." }`. If the deleted account was active, promotes the first remaining account to `is_active = true`.
- **Response (`200 OK`)**: Returns `{ "items": [...], "accounts": [...] }`.

