"""How many of the chat's lights cast shadows, and keeping them within what EEVEE can fit."""


# EEVEE keeps the shadows of every shadow-casting light in one fixed pool; past about this many lights the pool fills
# ("Shadow buffer full") and shadows go missing in the render. Lights past it lose their shadow, weakest first.
SHADOW_LIGHTS_MAX = 12
# Six large area lights already overflowed the default 512 MB pool in a lit hangar (about 2250 / 2048 pages), while
# five smaller ones did not; the count does not predict it, so any shadow-casting light of the chat's raises the pool.
SHADOW_POOL = "1024"
SHADOWS_NOTE = ("%d of your lights cast shadows; EEVEE fits about %d. Turn shadows off on small decorative lights "
                "(light.use_shadow = False).")


class ShadowLimit:
    def limit_shadows(self):
        """Turn off the shadow of the chat's weakest lights past ``SHADOW_LIGHTS_MAX`` (suns keep theirs); returns
        their names."""
        lights = [o for o in self._objects() if o.type == "LIGHT" and getattr(o.data, "use_shadow", False)]
        eevee = getattr(self.scene, "eevee", None)
        if lights and eevee is not None and hasattr(eevee, "shadow_pool_size"):
            try:
                if int(eevee.shadow_pool_size) < int(SHADOW_POOL):
                    eevee.shadow_pool_size = SHADOW_POOL
            except (TypeError, ValueError):  # an EEVEE without these sizes keeps its own
                pass
        if len(lights) <= SHADOW_LIGHTS_MAX:
            return []
        lights.sort(key=lambda o: (o.data.type != "SUN", -o.data.energy))
        trimmed = []
        for obj in lights[SHADOW_LIGHTS_MAX:]:
            if obj.data.type == "SUN":
                continue
            obj.data.use_shadow = False
            trimmed.append(obj.name)
        self.shadows_off.extend(n for n in trimmed if n not in self.shadows_off)
        return trimmed
