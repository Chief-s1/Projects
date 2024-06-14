## DDoS Detection using Machine Learning Algorithms
▪ A distributed denial of service (DDoS) attack is a malicious attempt to make an online service unavailable to users, usually by temporarily interrupting or suspending the services of its hosting server DDoS detection using machine learning involves training algorithms on network traffic data to identify patterns indicative of attacks. These models can distinguish between normal and malicious traffic, enabling timely mitigation of Distributed Denial of Service (DDoS) attacks.

Various Types of DDoS attack types:

1)UDP Flood
2)TCP_SYN Flood
3)ICMP Flood

▪ Dataset :  The cleaned.csv file is KD99 generated dataset. It is located in 'dataset' directory

▪ Packages             : numpy, sklearn, pickle, tqdm, pandas, seaborn and matplotlib.

▪ Techniques           : K-Nearest Neighbours, Decision tree, Multi-layer Perceptron and Logistic Regression. 

▪ Platforms            : Jupyter Notebook and IDLE

▪ 3 .ipynb files on 3 different DDoS attacks implementing all Machine Learning Algorithms in each file.

▪ 2 .py files which is train.py and test.py for fitting our best models with trained and test data.  
  

In each .ipynb files I have distinguished each model's performance and used the best 2 models in train.py. 

Train all the models First in your own machine first before testing any case

TRAINING OUR MODEL (This will take certain amount of time)
   go to Anaconda prompt and execute the below command
 
      python train.py icmp 0

   You can even change the protocol from the choices "udp", "tcp_syn" and "icmp". 
   So if you want to use tcp_syn protocol type and train it with KNN model type:

      python train.py tcp_syn 0
   
   At the end of executing this command you will get something like this:

    Data preprocessing done.
    The model has been fit.
    Save the fitted model?(y/n)

   asking you to save the pre-trained model for future use. type "y" and press enter
   The model is saved using pickle as .sav file and will be used it while testing.
   You can find the .sav files under 'saved_model' directory. 

   TESTING OUR MODEL
   This is fast but a little tricky
   You have to ensure how many parameters you input for testing out the class.
    
    python test.py tcp_syn -1.5 1.0 2.0 30.0 1.0
    
   This will use the tcp_syn pre-trained model and test the given parameters on it.
   Now each protocol has different parameter length as input. While tcp_syn protocol takes
   a length of 5 float value inputs others may take different inputs.
   
   NOTE:
   
	ICMP takes 7 ARGUMENTS
   7 parameters you need to provide for the script to classify ICMP network traffic:
   Service: The type of ICMP service (e.g., eco_i, ecr_i, tim_i, urp_i).
   Duration: The duration of the network activity in seconds.
   Source Bytes: The number of bytes sent from the source.
   Wrong Fragments: The number of wrong fragments detected.
   Count: The count of packets exchanged.
   Urgent: The number of urgent flags set.
   Number of Compromised: The number of compromised systems.
	
	UDP takes 5 ARGUMENTS
   These scenarios include the following parameters for UDP traffic:
   Duration: Represents the duration of the communication session.
   Service: Indicates the type of service being utilized.
   Source Bytes: Amount of data transmitted from the source.
   Destination Bytes: Amount of data transmitted to the destination.
   Count: Number of connections to the same host during the session.
	
	TCP_SYN takes 5 ARGUMENTS
   These scenarios include the following parameters for TCP_SYN traffic:
   SYN Packet Rate: High rates indicate a potential SYN flood attack.
   Source IP Address Count: High counts suggest IP spoofing or distributed attack.
   Destination Port: Targeted ports can indicate attacks on specific services.
   SYN-ACK Response Rate: Low rates indicate the target is overwhelmed.
   Incomplete Connection Count: High numbers indicate resources tied up by attack.
   

These are few sample attributes of each attack. You can test and compare the result with predicted ones.
        
   python test.py tcp_syn -1.5 1.0 2.0 1.0 1.0
	python test.py tcp_syn -1.5 1.0 2.0 30.0 1.0
	python test.py icmp 0.0 0.0 30.0 0.0 1.0 0.0 0.0
	python test.py udp 45.0 -0.3 45.0 236.0 2.0



























