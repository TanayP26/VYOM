# Problem Statement

Modern satellites continuously generate large volumes of telemetry from subsystems such
as power, thermal control, communication and attitude control. Identifying abnormal
behaviour in this data is difficult because normal operating conditions vary over time,
while early-stage faults may appear only as small statistical deviations.

VYOM is a Statistical Machine Learning based satellite health intelligence and anomaly
early-warning platform. The system aims to learn normal telemetry behaviour from
historical satellite data and detect unusual patterns using statistical and machine
learning techniques.

Instead of only giving a binary alert, VYOM is designed to provide an anomaly score,
affected telemetry channel and supporting statistical evidence for operator review.

The objective is to help satellite operators identify possible subsystem problems early,
reduce unnecessary alerts and monitor spacecraft health more efficiently.
