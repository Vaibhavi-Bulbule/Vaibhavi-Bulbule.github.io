# Story: Cancel a passenger segment from a PNR

**As** a Sabre reservation agent
**I want** to cancel a single segment on an existing PNR
**So that** the customer keeps the rest of their itinerary intact.

## Acceptance criteria

**Given** a PNR with at least two confirmed segments
**When** the agent cancels one segment by its segment number
**Then** the segment status becomes `XX` (cancelled)
**And** the remaining segments are unchanged
**And** an audit entry is written with the agent ID, segment ID, and timestamp.

**Given** a PNR with a single segment
**When** the agent attempts to cancel it
**Then** the call is rejected with `LAST_SEGMENT_PROTECTED`
**And** no audit entry is written.

**Given** a PNR that does not exist
**When** the agent attempts to cancel a segment on it
**Then** the call is rejected with `PNR_NOT_FOUND`.

## Notes

- The PNR record store is an existing port; assume an interface
  `PnrRepository` with `findByLocator(String locator)` and `save(Pnr pnr)`.
- The audit sink is an existing port `AuditLog` with
  `record(AuditEntry entry)`.
- No HTTP layer in scope - service class only, plus tests.
