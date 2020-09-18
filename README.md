## AWS Proxy

AWS Proxy is a tool that utilizes AWS CloudFormation to deploy HTTP proxy servers. In just minutes, hundreds of EC2 private proxies can be spun up.


### Requirements

* python3
* boto3
* AWS CLI configured with credentials. 

### Access to Proxies
All proxies are HTTP proxies running on port 8080. 

Access to proxies is restricted using EC2 security groups. By default, only the system running the tool can talk the proxies (the proxies can talk to each other). The IP address of the system running the script is determined using ipinfo.io. If the system running the script is behind a NAT gateway with a pool of IP Address, access may not work correctly. 

The secondary proxies can be accessed directly or via the head proxy. The head proxy will route requests to the secondary proxies on a round-robin basis. 

SSH to the proxies is also available based on the same security group rules as the proxy. A new SSH key is generated and stored in ``outputs/{region}/`` each time a new stack is spun up.

### Limits

Each AWS region has its own limits on the number of On-Demand EC2 CPUs that can be used. At the time of writing, the following limits were in place for an account that has never requested an increase:

``us-east-1`` - 1280 CPUs or 640 t3.nano instances

``us-east-2`` - 64 CPUs or 32 t3.nano instances

``us-west-1`` - 64 CPUs or 32 t3.nano instances

``us-west-2`` -  64 CPUs or 32 t3.nano instances

The tool spins up a primary proxy, so if no other instances exist in a region when the script is run, 31 or 639 proxies could be specified depending on region.

### Usage

python3 aws_proxy.py operation {region} {num_proxies}

Note that ``num_proxies`` is only valid for the ``start`` operation. 

##### Operations
``cleanup`` - Remove leftover cloud formation template files. 

``health`` - Ensure the proxies are working as intended. Utilizes files in ``outputs/{region}`` to determine current proxies. 

``status`` - Get the current status of the CloudFormation stack.

``start`` - Starts a CloudFormation stack in the ``region`` specified with ``num_proxies`` proxies. Defaults to using ``us-east-1`` and 3 proxies.    
 
 
### Implementation Details

haproxy is utilized as primary proxy and routes requests round-robin to Apache back-end servers. The default behavior of Apache when it receives a proxy request is to send the request based on the ``Host`` HTTP request header. This makes sending requests to virtual hosts without public DNS impossible. The Apache configuration used allows users to specify a ``Host-Override`` header which the virtual host to be accessed. The configuration will replace the Host header in the resulting proxied request. 