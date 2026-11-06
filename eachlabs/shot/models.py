"""The models a shot video uses, with their prices and limits. No ``bpy``."""

VIDEO = {
    "slug": "bytedance-seedance-2-5-reference-to-video",
    "label": "Seedance 2.5",
    "per_second": {"480p": 0.155, "720p": 0.305, "1080p": 0.695},
    "max_images": 9,
    "min_seconds": 4,
    "max_seconds": 15,
}
PHOTO = {"slug": "bytedance-seedream-v5-pro-edit", "price": 0.045}
ASPECTS = ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
RESOLUTIONS = ("480p", "720p", "1080p")
