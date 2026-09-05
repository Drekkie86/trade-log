# V1 Audit Export Security Review

Package 5 already omitted configured secret keys and exported only secret-presence booleans. Package 6 strengthens this because provider/runtime error text can theoretically contain a secret value even when the configuration section itself is safe.

The export now recursively redacts every configured known secret value from the complete snapshot before serialization, including nested command-deck/provider/error content.

Known secret classes currently include Massive API key, ThetaData API key, OIDC client secret and oauth2-proxy cookie secret. Tests inject secrets into nested diagnostic text and require the exported artifact to contain no raw secret value.

Audit artifacts remain operational/research evidence, not public artifacts; deployment stores them in a restricted persistent directory.
