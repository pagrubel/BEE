import boto3
import subprocess
from subprocess import Popen
import time
from termcolor import colored, cprint


class BeeAWS(object):
    def __init__(self, job_id, name, bee_aws_conf, job_conf, security_group, placement_group):
        
        self.ec2_client = boto3.client('ec2')
        self.__job_name = 'job{}'.format(str(job_id).zfill(3))
        self.hostname = name
        self.__ami_image = bee_aws_conf['ami_image']
        self.__aws_key_path = bee_aws_conf['aws_key_path']
        self.__aws_key_name = bee_aws_conf['aws_key_name']
        self.__instance_type = bee_aws_conf['instance_type']
        self.__security_group = security_group
        self.__placement_group = placement_group
        
        # Will be set after running
        self.__instance_id = 0
        
        self.__host = ""
        self.private_ip = ""
        
        self.__user_name = "ubuntu"
        
        self.vm_shared_dir = "/home/ubuntu/vmshare"

        self.__docker = ""

        self.__job_conf = job_conf

        # Output color list                                                                                                                                
        self.__output_color_list = ["magenta", "cyan", "blue", "green", "red", "grey", "yellow"]
        self.__output_color = self.__output_color_list[job_id % 7]

    def start(self):
        resp = self.ec2_client.run_instances(ImageId = self.__ami_image,
                                             MinCount = 1,
                                             MaxCount = 1,
                                             KeyName = self.__aws_key_name,
                                             SecurityGroups = [self.__security_group, 'default'],
                                             Placement = {'GroupName':self.__placement_group},
                                             InstanceType = self.__instance_type)
                             


        self.__instance_id = resp['Instances'][0]['InstanceId']
        cprint('[' + self.__job_name + '] Start instance:' + self.__instance_id, self.__output_color)
        
        # Setup name tag of this instance
        self.ec2_client.create_tags(Resources = [self.__instance_id], 
                                    Tags=[{'Key':'Name', 'Value':self.hostname}])

    def get_hostname(self):
        return self.hostname 
        
    def getInstance(self):
        resp = self.ec2_client.describe_instances(InstanceIds = [self.__instance_id])
        inst = resp['Reservations'][0]['Instances'][0]
        return inst


    def wait(self):
        resp = self.ec2_client.describe_instances(InstanceIds = [self.__instance_id])
        
        while resp['Reservations'][0]['Instances'][0]['State']['Name'] != 'running':
            resp = self.ec2_client.describe_instances(InstanceIds = [self.__instance_id])
        resp = self.ec2_client.describe_instances(InstanceIds = [self.__instance_id])
        
        self.__host = resp['Reservations'][0]['Instances'][0]['PublicDnsName']
        self.private_ip = resp['Reservations'][0]['Instances'][0]['PrivateIpAddress']

    def run(self, command, pfwd = '-1', async = False):
        exec_cmd = ["ssh",
                    "-o StrictHostKeyChecking=no",
                    "-o ConnectTimeout=300",
                    "-o UserKnownHostsFile=/dev/null",
                    "-q",
                    "-i", "{}".format(self.__aws_key_path),
                    "{}@{}".format(self.__user_name, self.__host),
                    "-x"]
        if pfwd != '-1':
            exec_cmd.insert(7, "-L {}:localhost:{}".format(pfwd, pfwd))
        cmd = exec_cmd + command
        
        #print(" ".join(cmd))
        
        if async:
            Popen(cmd)
        else:
            subprocess.call(cmd)

    def parallel_run(self, command, nodes, pfwd = '-1', async = False):
        cmd = ["mpirun",
               "-host"]
        node_list = ""
        for node in nodes:
            node_list = node_list + node.hostname + ","
        cmd.append(node_list)
        cmd = cmd + command
        self.run(cmd, pfwd, async)

    def set_hostname(self):
        cprint('[' + self.hostname + '] Set hostname.', self.__output_color)
        cmd = ["sudo",
               "hostname",
               self.hostname]
        self.run(cmd)

    def add_host_list(self, private_ip, hostname):
        cprint('[' + self.hostname + '] Add entry to hostfile.', self.__output_color)
        cmd = ["echo",
               "\"{} {}\"".format(private_ip, hostname),
               "|",
               "sudo tee --append",
               " /etc/hosts"]
        self.run(cmd)

    def create_shared_dir(self):
        cprint('[' + self.hostname + '] Create shared directory.', self.__output_color)
        cmd = ["mkdir",
               "{}".format(self.vm_shared_dir)]
        self.run(cmd)

    def mount_efs(self, efs_id):
        
        cprint('[' + self.hostname + '] Mount efs.', self.__output_color)
        my_session = boto3.session.Session()
        my_region = my_session.region_name

        cmd = ["sudo",
               "mount",
               "-t nfs4",
               "-o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2",
               "{}.efs.{}.amazonaws.com:/ {}".format(efs_id, my_region, self.vm_shared_dir)]
        self.run(cmd)

    def change_ownership(self):
        cprint("["+self.hostname+"]: Update ownership of shared directory.", self.__output_color)
        cmd = ["sudo",
               "chown",
               "-R",
               "ubuntu:ubuntu",
               "{}".format(self.vm_shared_dir)]
        self.run(cmd)


    def copy_file(self, src_path, dist_path):
        cprint("["+self.hostname+"]: Copy file:"+src_path+" --> "+dist_path+".", self.__output_color)
        cmd = ["scp",
               "-i", "{}".format(self.__aws_key_path),
               "{}".format(src_path),
               "{}@{}:{}".format(self.__user_name, self.__host, dist_path)]
        #print(" ".join(cmd))
        subprocess.call(cmd)


    # Docker related functions:
    def add_docker_container(self, docker):
        self.__docker = docker

    def get_dockerfile(self, vms):
        cprint("["+self.hostname+"]: pull docker image in parallel.", self.__output_color)
        self.parallel_run(self.__docker.get_dockerfile(), vms)

    def get_docker_img(self, vms):
        self.parallel_run(self.__docker.get_docker_img(), vms)

    def build_docker(self, vms):
        self.parallel_run(self.__docker.build_docker(), vms)

    def start_docker(self, exec_cmd):
        cprint("["+self.hostname+"]: start docker container.", self.__output_color)
        self.run(self.__docker.start_docker(exec_cmd))

    def docker_update_uid(self, uid):
        cprint("["+self.hostname+"][Docker]: update docker user UID.", self.__output_color)
        self.run(self.__docker.update_uid(uid))
    
    def docker_update_gid(self, gid):
        cprint("["+self.hostname+"][Docker]: update docker user GID.", self.__output_color)
        self.run(self.__docker.update_gid(gid))
    
    def docker_copy_file(self, src_path, dist_path):
        cprint("["+self.hostname+"][Docker]: copy file to docker" + src_path + " --> " + dist_path +".", self.__output_color)
        self.run(self.__docker.copy_file(src_path, dist_path))

    def docker_seq_run(self, exec_cmd, pfwd = '-1', async = False):
        cprint("["+self.hostname+"][Docker]: run script:"+exec_cmd+".", self.__output_color)
        self.run(self.__docker.run([exec_cmd]), pfwd, async)

    def docker_para_run(self, exec_cmd, vms, pfwd = '-1', async = False):
        cprint("["+self.hostname+"][Docker]: run parallel script:" + exec_cmd + ".", self.__output_color)
        np = int(self.__job_conf['proc_per_node']) * int(self.__job_conf['num_of_nodes'])
        cmd = ["mpirun",
               "--allow-run-as-root",
               "--mca btl_tcp_if_include eth0",
               "--hostfile /root/hostfile",
               "-np {}".format(np)]
        cmd = cmd + [exec_cmd]
        self.run(self.__docker.run(cmd), pfwd, async)

    def docker_make_hostfile(self, vms, tmp_dir):
        cprint("["+self.hostname+"][Docker]: prepare hostfile.", self.__output_color)
        hostfile_path = "{}/hostfile".format(tmp_dir)
        cmd = ["rm",
               hostfile_path]
        print(" ".join(cmd))
        subprocess.call(cmd)

        cmd = ["touch",
               hostfile_path]
        print(" ".join(cmd))
        subprocess.call(cmd)

        for vm in vms:
            print(vm.get_hostname())
            cmd = ["ssh",
                   "localhost",
                   "-x",
                   "echo",
                   "\"{} slots={} \"".format(vm.get_hostname(), self.__job_conf['proc_per_node']),
                   "|",
                   "tee --append",
                   hostfile_path]
            print(" ".join(cmd))
            subprocess.call(cmd)
