*** Settings ***
Library    SSHLibrary

*** Variables ***
${HOST}    zitadel.example.org

*** Test Cases ***
Check if zitadel is installed correctly
    ${output}  ${rc} =    Execute Command    add-module ${IMAGE_URL} 1
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}  0
    &{output} =    Evaluate    ${output}
    Set Suite Variable    ${module_id}    ${output.module_id}

Check if zitadel can be configured
    ${rc} =    Execute Command    api-cli run module/${module_id}/configure-module --data '{"host":"${HOST}","http2https":true,"lets_encrypt":false}'
    ...    return_rc=True  return_stdout=False
    Should Be Equal As Integers    ${rc}  0

Check if zitadel works as expected
    ${rc} =    Execute Command    bash -c 'for i in $(seq 1 60); do curl -k -s -o /dev/null -f --resolve ${HOST}:443:127.0.0.1 https://${HOST}/ && exit 0; sleep 5; done; exit 1'
    ...    return_rc=True  return_stdout=False
    Should Be Equal As Integers    ${rc}  0

Check if directory login defaults to disabled
    ${output}    ${rc}=    Execute Command    api-cli run module/${module_id}/get-configuration --data '{}'
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}    0    ${output}
    ${config}=    Evaluate    json.loads($output)    modules=json
    Should Be Empty    ${config}[ldap_domain]
    Should Be Empty    ${config}[ldap_additional_domains]
    Should Be Empty    ${config}[ldap_organizations]
    Should Not Be True    ${config}[ldap_token_configured]

Check if zitadel is removed correctly
    ${rc} =    Execute Command    remove-module --no-preserve ${module_id}
    ...    return_rc=True  return_stdout=False
    Should Be Equal As Integers    ${rc}  0
