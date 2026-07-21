import { ApiOutlined, FileSearchOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Col, Layout, Row, Space, Spin, Tag, Typography } from 'antd'

import { fetchLiveHealth } from './api/client'

const { Header, Content } = Layout
const { Title, Paragraph, Text } = Typography

function App() {
  const health = useQuery({
    queryKey: ['health', 'live'],
    queryFn: fetchLiveHealth,
  })

  return (
    <Layout className="app-shell">
      <Header className="app-header">
        <div className="brand-mark">S</div>
        <div>
          <Text className="brand-name">SmartHR</Text>
          <Text className="brand-subtitle">AI 简历筛选工作台</Text>
        </div>
      </Header>

      <Content className="app-content">
        <section className="hero-panel">
          <Tag color="blue">MVP 工程骨架</Tag>
          <Title>让简历筛选有依据、可复核</Title>
          <Paragraph>
            从职位标准、批量解析到证据化匹配，AI 提供建议，招聘专员保留最终判断权。
          </Paragraph>
          <Space>
            <Button type="primary" icon={<FileSearchOutlined />} disabled>
              创建筛选职位
            </Button>
            <Text type="secondary">业务功能将在后续步骤开放</Text>
          </Space>
        </section>

        <Row gutter={[20, 20]}>
          <Col xs={24} lg={8}>
            <Card title="服务状态" extra={<ApiOutlined />} className="status-card">
              {health.isPending && <Spin size="small" />}
              {health.isError && <Alert type="error" message={health.error.message} showIcon />}
              {health.isSuccess && (
                <Space>
                  <Tag color="success">API 正常</Tag>
                  <Text type="secondary">{health.data.status}</Text>
                </Space>
              )}
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <Card title="隐私边界" extra={<SafetyCertificateOutlined />} className="status-card">
              <Paragraph>原始简历保存在受控本地目录，外部模型只接收脱敏文本。</Paragraph>
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <Card title="当前阶段" extra={<FileSearchOutlined />} className="status-card">
              <Paragraph>工程骨架搭建中，下一步实现登录和职位标准版本。</Paragraph>
            </Card>
          </Col>
        </Row>
      </Content>
    </Layout>
  )
}

export default App
