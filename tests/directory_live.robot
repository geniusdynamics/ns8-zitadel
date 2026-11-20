*** Settings ***
Library    SSHLibrary

*** Variables ***
${ZITADEL_DIRECTORY_FIXTURE}    ${EMPTY}
${ZITADEL_DIRECTORY_SCENARIO}    online

*** Test Cases ***
Validate existing Zitadel directory fixtures
    Skip If    not $ZITADEL_DIRECTORY_FIXTURE    No existing directory test fixture was supplied
    ${script}    ${rc}=    Execute Command    mktemp /tmp/ns8-zitadel-directory.XXXXXX
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}    0
    TRY
        Put File    ${CURDIR}/zitadel_directory_login.py    ${script}
        ${fixture_arg}=    Evaluate    shlex.quote($ZITADEL_DIRECTORY_FIXTURE)    modules=shlex
        ${scenario_arg}=    Evaluate    shlex.quote($ZITADEL_DIRECTORY_SCENARIO)    modules=shlex
        ${output}    ${error}    ${rc}=    Execute Command
        ...    python3 ${script} ${fixture_arg} ${scenario_arg}
        ...    return_stderr=True    return_rc=True
        Should Be Equal As Integers    ${rc}    0    ${output}\n${error}
    FINALLY
        Execute Command    rm -f -- ${script}
    END
