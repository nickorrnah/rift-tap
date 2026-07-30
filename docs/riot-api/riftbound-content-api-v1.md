# Riftbound Content API v1

## Get Riftbound Content

Retrieves Riftbound content data.

### Endpoint

```http
GET /riftbound/content/v1/contents
```

### Response

**Return type:** `RiftboundContentDTO`

#### `RiftboundContentDTO`

| Field | Type | Description |
|---|---|---|
| `game` | `string` | Game name |
| `version` | `string` | Content version |
| `lastUpdated` | `string` | ISO timestamp of the most recent content update |
| `sets` | `List<SetDTO>` | Collection of card sets |

#### `SetDTO`

| Field | Type | Description |
|---|---|---|
| `id` | `string` | Set ID |
| `name` | `string` | Set name |
| `cards` | `List<CardDTO>` | Cards contained in the set |

#### `CardDTO`

| Field | Type | Description |
|---|---|---|
| `id` | `string` | Card ID |
| `collectorNumber` | `long` | Collector number |
| `set` | `string` | Set identifier or name |
| `name` | `string` | Card name |
| `description` | `string` | Card description |
| `type` | `string` | Card type |
| `rarity` | `string` | Card rarity |
| `faction` | `string` | Card faction |
| `stats` | `CardStatsDTO` | Card statistics |
| `keywords` | `List<string>` | Card keywords |
| `art` | `CardArtDTO` | Card artwork metadata |
| `flavorText` | `string` | Card flavor text |
| `tags` | `List<string>` | Card tags |

#### `CardStatsDTO`

| Field | Type | Description |
|---|---|---|
| `energy` | `long` | Energy value |
| `might` | `long` | Might value |
| `cost` | `long` | Cost value |
| `power` | `long` | Power value |

#### `CardArtDTO`

| Field | Type | Description |
|---|---|---|
| `thumbnailURL` | `string` | Thumbnail image URL |
| `fullURL` | `string` | Full-size image URL |
| `artist` | `string` | Artist name |

## Query Parameters

| Name | Type | Required | Default | Description |
|---|---|---:|---|---|
| `locale` | `string` | No | `en` | Specifies the language and regional settings for the response. Use a locale code. During beta, only `en` is available. |

## Region

The documented execution region is:

```text
AMERICAS
```

## Authentication

An API key can be included using one of the following methods:

- Query parameter
- Header parameter
- Not required

The API documentation interface shows **Query Param** selected by default.

## Error Responses

| HTTP Status | Reason |
|---:|---|
| `400` | Bad request |
| `401` | Unauthorized |
| `403` | Forbidden |
| `404` | Data not found |
| `405` | Method not allowed |
| `415` | Unsupported media type |
| `429` | Rate limit exceeded |
| `500` | Internal server error |
| `502` | Bad gateway |
| `503` | Service unavailable |
| `504` | Gateway timeout |
