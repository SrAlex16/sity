-- WirePlumber ignora el loopback completamente (lo usa Vivaldi/ALSA directamente)
table.insert(alsa_monitor.rules, {
  matches = {
    { { "device.name", "equals", "alsa_card.platform-snd_aloop.0" } },
  },
  apply_properties = {
    ["device.disabled"] = true,
  },
})
