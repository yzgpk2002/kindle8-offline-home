/* Fixed-action launcher for the manual-only service; explicitly approved.
 * Install root:javausers 4750.
 * No shell, caller-controlled paths, environment, or arbitrary commands.
 */
#include <unistd.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <grp.h>
int main(int argc, char **argv) {
    uid_t caller=getuid();
    if ((caller!=0 && caller!=9000) || argc!=2) return 64;
    if (strcmp(argv[1],"start") && strcmp(argv[1],"stop") && strcmp(argv[1],"status")) return 64;
    const char *action=argv[1];
    if (chdir("/") || setgroups(0,NULL) || setgid(0) || setuid(0)) return 77;
    if (!strcmp(action,"stop") && access("/var/local/kt3-hfp-lab/session-lock",F_OK)==0) {
        fputs("Audio session active; wait for automatic restore before stopping.\n",stderr);
        return 75;
    }
    char *args[]={"/sbin/initctl",(char *)action,"kt3-home-manual",NULL};
    char *env[]={"PATH=/usr/bin:/bin:/usr/sbin:/sbin","LANG=C",NULL};
    execve(args[0],args,env);
    perror("manual-control");
    return 71;
}
