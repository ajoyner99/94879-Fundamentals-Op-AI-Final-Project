# 94-879 Challenge B1 README


### Reset Procedure Before Experiments

Clear the lag
Windows (Command Prompt):
```cmd
docker exec -it broker /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --group featurizer_group --topic ticks.raw --reset-offsets --to-latest --execute
docker exec -it broker /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group featurizer_group  
```