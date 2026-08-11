# 🌬️ Fan Groups

Fan Groups work similarly to a simplified version of the [Generic Thermostat](https://www.home-assistant.io/integrations/generic_thermostat/). This feature groups all fans within an area—whether you have one or many—and allows you to monitor an [aggregate sensor](aggregation.md) of a selected `device_class` such as `temperature` 🌡️, `humidity` 💧, or `co2` 🫁.

The fans will automatically turn `on` 🔛 when the tracked sensor’s value rises above a configured `setpoint`, and turn `off` 🔘 when it falls below.

## ⚙️ Configuration Options

| Option                 | Type    | Default   | Description                                                                 |
|------------------------|--------|-----------|-----------------------------------------------------------------------------|
| Required state         | string | `extended` | Area must be in this state for fans to activate.                            |
| Tracked device class   | string | `temperature` | Aggregate device class to monitor (e.g., `temperature`, `humidity`, `co2`). |
| Setpoint               | number | `0`       | Value threshold at which fans turn on/off.                                   |

When the area becomes clear, Fan Control turns the group off regardless of the tracked value.

## 🛠️ Example Use Cases

* Turning fans on when it’s too hot 🔥
* Activating bathroom exhaust fans when humidity is too high 💦
* Turning on ventilation fans if CO2 levels become elevated 🏭
