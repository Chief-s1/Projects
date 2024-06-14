import numpy as np
import sys
import pickle
import warnings
warnings.filterwarnings("ignore", message="X does not have valid feature names")

def icmp_test(attributes):
    model = pickle.load(open("./saved_model/icmp_data.sav", 'rb'))
    result = model.predict([attributes])
    if result == 1:
        print("Attack is detected.")
    else:
        print("No attack is detected.")

def udp_test(attributes):
    model = pickle.load(open("./saved_model/udp_data.sav", 'rb'))
    result = model.predict([attributes])
    if result == 1:
        print("Attack is detected.")
    else:
        print("No attack is detected.")

def tcp_syn_test(attributes):
    model = pickle.load(open("./saved_model/tcp_syn_data.sav", 'rb'))
    result = model.predict([attributes])
    if result == 1:
        print("Attack is detected.")
    else:
        print("No attack is detected.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("Insufficient number of arguments. Format: python test.py <protocol> <attribute1> <attribute2> ...")

    protocol = sys.argv[1]
    attributes = [float(arg) for arg in sys.argv[2:]]

    if protocol == "icmp": 
        icmp_test(attributes)
    elif protocol == "tcp_syn":
        tcp_syn_test(attributes)
    elif protocol == "udp":
        (udp_test(attributes))
    else:
        sys.exit("Incorrect protocol has been chosen for testing. Try again.")
