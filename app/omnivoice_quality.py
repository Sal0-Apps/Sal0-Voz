"""Versioned CPU profiles, frozen in each job instead of changed on resume."""

LEGACY_PROFILE = "legacy-32"
MAXIMUM_PROFILE = "maximum-64-v1"


def maximum_quality(project):
    return project.get("engine") == "omnivoice" and project.get("omnivoice_profile") == MAXIMUM_PROFILE


def generation_options(profile):
    if profile == LEGACY_PROFILE:
        return {"num_step": 32, "normalize_text": False, "preprocess_prompt": True}
    if profile != MAXIMUM_PROFILE:
        raise ValueError("Perfil do OmniVoice desconhecido. Atualize o aplicativo antes de retomar.")
    # 64 is the highest step count exposed by the upstream demo. Keep the
    # trained sampling defaults: increasing every knob does not improve quality.
    return {
        "num_step": 64, "guidance_scale": 2.0, "t_shift": 0.1,
        "layer_penalty_factor": 5.0, "position_temperature": 5.0,
        "class_temperature": 0.0, "denoise": True,
        "normalize_text": False, "preprocess_prompt": False,
        "postprocess_output": False, "fade_duration": 0.01, "pad_duration": 0.1,
        # The app, not an invisible 15-second backend split, owns overload
        # recovery and checkpoints. A native-context guard runs before attention.
        "audio_chunk_duration": 0.0, "audio_chunk_threshold": 1_000_000_000.0,
    }
