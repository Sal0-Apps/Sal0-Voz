"""New engine settings frozen per job; never downgrade a resumed voice."""
POCKET_PROFILE = "pocket-pt-24l-fp32-5-v1"
DRAMA_PROFILE = "drama3-q4-f32-router-bf16-head-disk8-v1"
PROFILES = {"pocket-pt": POCKET_PROFILE, "drama3": DRAMA_PROFILE}


def high_precision(project):
    return project.get("output_sample_width") == 3


def seed_for(request, reference_key):
    import hashlib
    import json
    material = json.dumps([request.get("model_seed", 0), request.get("quality_profile"),
                           reference_key, request["text"], request["language"]], ensure_ascii=False)
    return int(hashlib.sha256(material.encode()).hexdigest()[:8], 16)
