"""Generate the Keycloak realm from existing local secrets; never overwrite users."""
import json
import secrets
from pathlib import Path
root=Path(__file__).resolve().parent.parent
path=root/'.env'
values=dict(line.split('=',1) for line in path.read_text().splitlines() if line and not line.startswith('#'))
keys=['KEYCLOAK_ADMIN_PASSWORD','REQUESTER_PASSWORD','APPROVER_PASSWORD','GOVERNANCE_ADMIN_PASSWORD']
new={key:secrets.token_urlsafe(20) for key in keys if key not in values}
with path.open('a') as f:
    for key,value in new.items():f.write(key+'='+value+'\n')
values.update(new)
realm={
 'realm':'micro','enabled':True,'sslRequired':'none','registrationAllowed':False,
 'roles':{'realm':[{'name':name} for name in ['requester','approver','administrator']]},
 'clients':[{'clientId':'micro-app','enabled':True,'publicClient':True,'standardFlowEnabled':True,
             'directAccessGrantsEnabled':True,'redirectUris':['http://localhost:8080/auth/callback'],
             'webOrigins':['http://localhost:8080'],'attributes':{'pkce.code.challenge.method':'S256'},
             'protocolMappers':[{'name':'micro-audience','protocol':'openid-connect','protocolMapper':'oidc-audience-mapper','config':{'included.client.audience':'micro-app','id.token.claim':'false','access.token.claim':'true'}}]}],
 'users':[{'username':name,'enabled':True,'emailVerified':True,'firstName':name.title(),'lastName':'Demo','email':name+'@micro.local',
           'realmRoles':[role],'credentials':[{'type':'password','value':values[key],'temporary':False}]} for name,role,key in [('requester','requester','REQUESTER_PASSWORD'),('approver','approver','APPROVER_PASSWORD'),('administrator','administrator','GOVERNANCE_ADMIN_PASSWORD')]]
}
file=root/'keycloak'/'micro-realm.json';file.write_text(json.dumps(realm,indent=2));file.chmod(0o600)
print('Local identity realm prepared. Credentials are in .env; accounts: requester, approver, administrator.')
