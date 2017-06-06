from bee_vm import BeeVM
from host import Host
from docker import Docker
import time
import subprocess
import os

class BeeVMLauncher(object):
    def __init__(self, group_num, job_conf, bee_vm_conf, docker_conf):
        
        self.__hosts = bee_vm_conf['node_list']
        
        # User configuration
        self.__job_conf = job_conf
        self.__bee_vm_conf = bee_vm_conf
        self.__docker_conf = docker_conf
        self.__group_num = group_num

        # System configuration
        self.__user_name = os.getlogin()
        self.__bee_working_dir = "/home/{}/.bee".format(self.__user_name)
        self.__vm_key_path = self.__bee_working_dir + "/ssh_key/id_rsa"
        self.__base_img_path = self.__bee_working_dir + "/base_img/base_img"
        self.__base_data_img_path = self.__bee_working_dir + "/base_img/base_data_img"
        self.__data_img_path = "data.qcow2"
        self.__vm_img_dir = self.__bee_working_dir + "/vm_imgs"
        self.__tmp_dir = self.__bee_working_dir + "/tmp"

        # bee-vms
        self.__bee_vm_list = []

    def start(self):
        self.kill_all()
        network_mode = 1
        storage_mode = 3

        for host in self.__hosts:
            curr_rank = len(self.__bee_vm_list)
            
            img_path = "{}/img_{}_{}.qcow2".format(self.__vm_img_dir, self.__job_conf['job_name'], curr_rank)
            
            hostname = ""
            if curr_rank == 0:
                hostname = "{}-bee-master".format(self.__job_conf['job_name'])
            else:
                hostname = "{}-bee-worker{}".format(self.__job_conf['job_name'], str(curr_rank).zfill(3))
    
            bee_vm = BeeVM(self.__group_num, hostname, host, curr_rank, self.__job_conf, self.__bee_vm_conf, self.__vm_key_path, self.__base_img_path, img_path, network_mode, storage_mode)
            
            # Add new VM to host
            self.__bee_vm_list.append(bee_vm)
            bee_vm.set_master(self.__bee_vm_list[0])

        #if network_mode == 1:
        # <no extra work need to be done>   
            
        if network_mode == 2:
            star = False
            tree = True
            # P2P Configure network
            if star:
                for i in range(1,  len(self.hosts)):
                    self.__bee_vm_list[0].connect_to_me(self.__bee_vm_list[i]) 
            if tree:
                self.__bee_vm_list[0].connect_to_me(self.__bee_vm_list[1])
                #self.__bee_vm_list[0].connect_to_me(self.__bee_vm_list[2])
                #self.__bee_vm_list[0].connect_to_me(self.__bee_vm_list[3])
                #self.__bee_vm_list[1].connect_to_me(self.__bee_vm_list[4])
                #self.__bee_vm_list[1].connect_to_me(self.__bee_vm_list[5])
                #self.__bee_vm_list[1].connect_to_me(self.__bee_vm_list[6])
                #self.__bee_vm_list[1].connect_to_me(self.__bee_vm_list[7])
                #self.__bee_vm_list[2].connect_to_me(self.__bee_vm_list[8])
                #self.__bee_vm_list[2].connect_to_me(self.__bee_vm_list[9])
                #self.__bee_vm_list[2].connect_to_me(self.__bee_vm_list[10])
                #self.__bee_vm_list[2].connect_to_me(self.__bee_vm_list[11])
                #self.__bee_vm_list[3].connect_to_me(self.__bee_vm_list[12])
                #self.__bee_vm_list[3].connect_to_me(self.__bee_vm_list[13])
                #self.__bee_vm_list[3].connect_to_me(self.__bee_vm_list[14])
                #self.__bee_vm_list[3].connect_to_me(self.__bee_vm_list[15])
        
        if storage_mode == 1:
            self.__bee_vm_list[0].set_data_img(base_data_img_path, data_img_path)
            self.__bee_vm_list[0].create_data_img()
        
        # Start VMs
        for bee_vm in self.__bee_vm_list:
            bee_vm.create_os_img()
            bee_vm.start()

        time.sleep(60)


        # Setup hostname
        for bee_vm in self.__bee_vm_list:
            bee_vm.set_hostname()

        # Setup hosts file
        for host1 in self.__bee_vm_list:
            for host2 in self.__bee_vm_list:
                host2.add_host_list(host1.get_ip(), host1.get_hostname())

        # Setup storage
        if storage_mode == 1:
            self.__bee_vm_list[0].mount_data_img()
            workers = self.__bee_vm_list[1:]
            for bee_vm in workers:
                bee_vm.mount_master_data_img()
        if storage_mode == 2:
            for bee_vm in self.__bee_vm_list:
                self.__bee_vm_list.mount_nfs("ccs7-isilon2-10gige.darwin:/ifs/data/darwin_home/jieyangchen/vmshare2")
        if storage_mode == 3:
            for bee_vm in self.__bee_vm_list:
                bee_vm.mount_virtio()

        for bee_vm in self.__bee_vm_list:
            bee_vm.update_uid()
            bee_vm.update_gid()
            bee_vm.update_ownership()
        
        time.sleep(20)
        
        for bee_vm in self.__bee_vm_list:
            docker = Docker(self.__docker_conf)
            bee_vm.add_docker_container(docker)
    
        # Get Dockers ready in parallel
        self.__bee_vm_list[0].get_docker_img(self.__bee_vm_list)
       
        for bee_vm in self.__bee_vm_list:
            bee_vm.start_docker("/usr/sbin/sshd -D")
            #bee_vm.docker_update_uid()
            #bee_vm.docker_update_gid()

        # Copy run scripts (host --> BeeVM --> Docker container)
        # General sequential script
        master = self.__bee_vm_list[0]
        count = 0
        for run_conf in self.__job_conf['general_run']:
            host_script_path = run_conf['script_path']
            vm_script_path = '/home/ubuntu/{}_general_script_{}.sh'.format(self.__job_conf['job_name'], count)
            docker_script_path = '/root/{}_general_script_{}.sh'.format(self.__job_conf['job_name'], count)

            master.copy_file(host_script_path, vm_script_path)
            master.docker_copy_file(vm_script_path, docker_script_path)
            
            master.docker_seq_run(docker_script_path, pfwd = run_conf['port_fwd'], async = run_conf['async'])
            
            count = count + 1
        
        count = 0
        for run_conf in self.__job_conf['mpi_run']:
            host_script_path = run_conf['script_path']
            vm_script_path = '/home/ubuntu/{}_mpi_script_{}.sh'.format(self.__job_conf['job_name'], count)
            docker_script_path = '/root/{}_mpi_script_{}.sh'.format(self.__job_conf['job_name'], count)    
            for bee_vm in self.__bee_vm_list:
                bee_vm.copy_file(host_script_path, vm_script_path)
                bee_vm.docker_copy_file(vm_script_path, docker_script_path)
            
            # Generate hostfile and copy to container
            master.docker_make_hostfile(self.__bee_vm_list, self.__tmp_dir)
            master.copy_file(self.__tmp_dir + '/hostfile', '/home/ubuntu/hostfile')
            master.docker_copy_file('/home/ubuntu/hostfile', '/root/hostfile')
            # Run parallel script on all nodes
            master.docker_para_run(docker_script_path, self.__bee_vm_list, pfwd = run_conf['port_fwd'], async = run_conf['async'])
            
            count = count + 1
                
    def stop(self):
        for bee_vm in self.__bee_vm_list:
            bee_vm.kill()

    def kill_all(self):
        for host in self.__hosts:
            h = Host(host)
            h.kill_all_vms()