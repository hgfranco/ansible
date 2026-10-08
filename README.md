# Ansible

Repeatable configuration for the self-managed kubeadm cluster provisioned by
[hgfranco/terraform](https://github.com/hgfranco/terraform).
The study roadmap belongs in [cka-project](https://github.com/hgfranco/cka-project).

## What gets configured

| Stage | Result |
| --- | --- |
| AWS inventory | Finds running nodes by Terraform tags and reads their current addresses |
| Node preparation | Configures hostnames, swap, kernel networking, containerd, and Kubernetes packages |
| Control plane | Initializes one kubeadm control plane with a private API endpoint and local etcd |
| Networking | Installs checksum-verified Calico operator manifests and VXLAN networking with NetworkPolicy support |
| Workers | Joins workers with CA verification and temporary tokens, then revokes each token |
| Verification | Waits for the expected nodes, CoreDNS, and Calico to become healthy |

Node preparation and cluster creation are separate commands. Re-running bootstrap
does not reset an existing cluster. Existing web/database roles are separate from
the Kubernetes playbooks.

This setup supports Ubuntu 24.04 amd64 and one control plane. It is not highly
available. It does not yet provide etcd backups, PostgreSQL storage, EBS CSI, or
cloud start/stop automation. The live Spotify site remains outside this setup.
EKS manages its control plane: do not run these kubeadm playbooks against EKS nodes.

## Versions and configuration

Review [inventory/group_vars/kubernetes.yml](inventory/group_vars/kubernetes.yml):

- Kubernetes: 1.35.9, package revision 1.1, matching the CKA 1.35 minor version.
- Calico: v3.32.2 with pinned SHA-256 manifest checksums.
- VPC: 10.42.0.0/16; pods: 192.168.0.0/16; services: 10.96.0.0/12.
- Containerd: 2.2.x, with native configuration version 3, CRI, and systemd cgroups.
  The role uses the installed Ubuntu package; it does not downgrade it.

Network ranges must not overlap and must agree with Terraform. The playbook
validates the network ranges and private node addresses. It refuses mismatched
Kubernetes package versions rather than implicitly upgrading or downgrading.
Changing Kubernetes or CNI versions on an existing cluster requires a deliberate
upgrade procedure. Re-rendering the kubeadm file does not reconfigure an existing
API server. OS/containerd updates remain part of your package maintenance.

The [inventory](inventory/kubernetes.aws_ec2.yml) selects running EC2 instances in
us-east-1 tagged Project=kubernetes, ManagedBy=Terraform, and Role=control-plane
or worker. Change these filters alongside Terraform's tags for another cluster.
Groups use `ec2_tags.Role`. amazon.aws 11.4.0 still exports the deprecated `tags`
alias and emits its deprecation notice unconditionally; the associated reserved
variable warning can remain until the collection removes that alias.
Only one cluster should match. Run with the full inventory rather than a partial
--limit; workers need the control plane's host variables.

Private addresses are used for the API endpoint and node registration. Public IP
changes after stop/start affect SSH access only; AWS inventory refreshes each run.
Stop/start preserves disks. Terminating a control plane requires a restore or
rebuild plan; these playbooks do not restore data.

## Controller prerequisites

Use Ansible from your Mac with your normal SSH agent/configuration and local AWS
profile. The AWS profile needs ec2:DescribeInstances. No credentials are in the repo.

From the repository root, with your existing pipx installation (pipx requires an
absolute requirements path because it runs pip from its virtual environment):

~~~bash
pipx runpip ansible install -r "$PWD/requirements-controller.txt"
ansible-galaxy collection install -r requirements.yml
~~~

The tested controller is ansible-core 2.21.4. Verify with ansible --version.
Pass --private-key /path/to/FrancoTech.pem to commands if your agent/configuration
does not already supply it. Keep private keys outside the repository.

## ECR image authentication

Terraform attaches an EC2 instance profile granting ECR authentication and pull
access to the application repository. Enable the kubelet credential provider with
`kubernetes_node_ecr_credential_provider_enabled` in the Kubernetes group variables.
The role defaults to disabled for environments that do not use ECR.

The v1.35.0 binary download is unavailable upstream, so build the official release
from the commit pinned in [the Dockerfile](build/ecr-credential-provider/Dockerfile).
Docker builds a static Linux amd64 binary without installing Go on the controller.
From the repository root:

~~~bash
docker buildx build --target artifact \
  --output type=local,dest=.artifacts/ecr-credential-provider/v1.35.0 \
  build/ecr-credential-provider
shasum -a 256 .artifacts/ecr-credential-provider/v1.35.0/ecr-credential-provider
~~~

The checksum must match `kubernetes_ecr_credential_provider_sha256` before
provisioning. Ansible verifies the local file before copying it to each node;
compiled artifacts are ignored by Git. A fresh clone requires this build step.
If changing the source or toolchain, review the new checksum deliberately.

Preparation installs the helper and its configuration, adds kubelet's credential
provider flags, and preserves `--node-ip`. Nodes are prepared one at a time.
Changes notify a kubelet restart; an unchanged repeat run does not restart it.
The helper obtains temporary ECR credentials using the node IAM role. No AWS
access keys or ECR passwords are stored in the repository or provider config.

## Run one stage at a time

The commands below are for an approved manual run. GitHub Actions does not execute
them against AWS or your nodes.

1. Review discovered names and groups:

~~~bash
ansible-inventory -i inventory/kubernetes.aws_ec2.yml --graph
~~~

Expect one control plane and two workers for the current Terraform environment.
Inventory discovery only reads AWS.

2. Review current SSH addresses and establish host trust, then check connectivity:

~~~bash
ansible-inventory -i inventory/kubernetes.aws_ec2.yml --host kubernetes-control
ansible -i inventory/kubernetes.aws_ec2.yml kubernetes -m ansible.builtin.ping
~~~

Read ansible_host for each node and verify/accept its SSH host key using your
normal SSH process. Host checking stays enabled. A new public IP may require
renewed host-key verification.

3. Prepare the nodes:

~~~bash
ansible-playbook -i inventory/kubernetes.aws_ec2.yml playbooks/prepare-kubernetes.yml
~~~

Review the tasks first. --check can preview some preparation changes but cannot
fully simulate fresh package installation. In check mode the full playbook skips
initialization, joins, networking installation, and readiness checks.

4. Initialize the cluster, configure networking, and join workers:

~~~bash
ansible-playbook -i inventory/kubernetes.aws_ec2.yml playbooks/kubernetes.yml
~~~

Existing configuration files prevent repeat init/join commands. A partial failure
stops without automatically resetting nodes; review its cause before retrying.
The ubuntu user receives a mode-0600 admin kubeconfig on the control plane.
It grants cluster-admin privileges.

5. Use kubectl on the control plane or optionally fetch a separate Mac kubeconfig:

~~~bash
ansible-playbook -i inventory/kubernetes.aws_ec2.yml playbooks/fetch-kubeconfig.yml
~~~

This writes ~/.kube/kubernetes-admin.conf with mode 0600 and points it to
https://127.0.0.1:16443. It does not change your default kubeconfig.
Open a tunnel in another terminal using the current control-plane public IP:

~~~bash
ssh -N -L 16443:127.0.0.1:6443 ubuntu@CONTROL_PLANE_PUBLIC_IP
~~~

Then:

~~~bash
kubectl --kubeconfig ~/.kube/kubernetes-admin.conf get nodes -o wide
~~~

The loopback address is included in the API certificate SANs, so TLS verification
stays enabled. The existing security group allows SSH from the administrator's
/32 and private traffic between nodes. No public API ingress is required.

## Validation and secrets

[GitHub Actions](.github/workflows/kubernetes-checks.yml) scans for secrets, lints
the new playbooks, checks syntax with an offline inventory, and tests network
validation and rendered kubeadm/Calico/containerd configuration. CI also loads the
runtime configuration using checksum-verified containerd 2.2.1; the role validates
it with the installed binary before replacing the configuration file. CI has no AWS
credentials and never connects to the EC2 nodes. These checks validate the code;
the first approved cluster run is still needed to verify runtime behavior.

Tests use documentation-only public IPs. AWS credentials and SSH keys stay
outside Git. Join tokens expire after 15 minutes, are hidden from logs, and are
revoked after each join attempt. Kubeconfigs stay outside the repo with mode 0600.
Application secrets can use AWS Secrets Manager or Parameter Store later.

## References

- [CKA version and objectives](https://training.linuxfoundation.org/certification/certified-kubernetes-administrator-cka/)
- [Kubernetes 1.35 releases](https://kubernetes.io/releases/1.35/)
- [Install kubeadm](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/)
- [Create a kubeadm cluster](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/)
- [Kubeadm configuration](https://v1-35.docs.kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta4/)
- [EC2 inventory](https://docs.ansible.com/projects/ansible/latest/collections/amazon/aws/aws_ec2_inventory.html)
- [Pinned Calico manifests](https://github.com/projectcalico/calico/tree/v3.32.2/manifests)
