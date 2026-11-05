from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from server.quiz import process_quiz_chapter


def test_quiz_verifies_work_cards_even_when_video_remains_incomplete():
    work={'type':'workid','jobid':'quiz-1'}
    video={'type':'video','jobid':'video-1'}
    client=Mock()
    client.get_job_list.side_effect=[([video,work,work],{'knowledgeid':'point'}),([video],{'knowledgeid':'point'})]
    client.study_work.return_value=SimpleNamespace(is_failure=lambda:False)
    assert process_quiz_chapter(client,{}, {'id':'point','has_finished':True})=='done'
    assert client.study_work.call_count==1
    client.study_video.assert_not_called()
    client.study_document.assert_not_called()
    client.study_read.assert_not_called()


def test_quiz_saved_but_unsubmitted_work_is_not_reported_complete():
    work={'type':'workid','jobid':'quiz-1'}
    client=Mock()
    client.get_job_list.return_value=([work],{'knowledgeid':'point'})
    client.study_work.return_value=SimpleNamespace(is_failure=lambda:False)
    with pytest.raises(ValueError,match='仍未被平台确认'):
        process_quiz_chapter(client,{}, {'id':'point'})


def test_quiz_mode_can_be_configured_through_ui_api(browser):
    user=browser.login()
    result=browser.send('/accounts/'+user['id']+'/config',{'study':{'study_mode':'quiz'}},'PUT')
    assert result.status_code==200 and result.json['config']['study']['study_mode']=='quiz'
