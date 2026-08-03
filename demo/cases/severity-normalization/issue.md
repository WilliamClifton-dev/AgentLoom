`normalize_severity(" high ")` raises `ValueError` because supported values are
uppercased without first removing surrounding whitespace.
