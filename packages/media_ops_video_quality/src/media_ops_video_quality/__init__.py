"""No-reference picture quality over sampled thumbnails (docs/extend_the_hub.md, visual quality).

Deterministic measurements plus one structured vision call. No AWS client is built here and
no agent framework is imported: packs sample the frames and pass in their Bedrock client.
"""
