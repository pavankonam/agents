---
name: unit-converter
description: "Converts between metric and imperial units for length, weight and temperature with the team's rounding rules. Use when the user asks to convert miles, km, pounds, kg, Fahrenheit or Celsius."
compatibility: Any model; no tools needed beyond load_skill.
---

# Unit conversion

Factors:

* 1 mile = 1.609344 km, 1 km = 0.621371 miles
* 1 pound = 0.45359237 kg, 1 kg = 2.20462 pounds
* Celsius = (Fahrenheit - 32) * 5 / 9, Fahrenheit = Celsius * 9 / 5 + 32

Rules:

1. Show the formula you used on one line.
2. Round the final value to exactly 2 decimal places.
3. Always end with the unit symbol (km, mi, kg, lb, °C, °F).
