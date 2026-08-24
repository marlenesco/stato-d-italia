# ADR 0002: versioned historical territories

Status: accepted.

`territory_id` identifies a logical administrative entity. `territory_version_id`
binds it to a validity/reference date, codes, parent relations and geometry. No
pipeline invents a historical crosswalk. Merge, split, abolition and transfer
produce an explicit series break unless a source-specific official mapping exists.

